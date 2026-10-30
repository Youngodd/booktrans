import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from booktrans.backends.base import AuthError, BackendError
from booktrans.web.app import create_app
from booktrans.web.jobs import JobStore
from tests.conftest import FakeBackend

TOKEN = "t0ken"
KEY = "sk-ant-test-1234567890abcdefghij"
H = {"X-Booktrans-Token": TOKEN}


@pytest.fixture
def make(tmp_path):
    pools = []

    def build(factory=lambda key, provider="api": FakeBackend(), **kw):
        pool = ThreadPoolExecutor(max_workers=1)
        pools.append(pool)
        app = create_app(tmp_path / "data", executor=pool, backend_factory=factory,
                         desktop=True, token=TOKEN, **kw)
        return TestClient(app, headers=H)
    yield build
    for p in pools:
        p.shutdown(wait=True)


def wait(client, job_id, states=("done", "failed", "paused"), timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["state"] in states:
            return j
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_token_required(make):
    c = make()
    assert TestClient(c.app).get("/api/config").status_code == 401
    assert TestClient(c.app, headers={"X-Booktrans-Token": "no"}).get("/api/config").status_code == 401
    assert c.get("/api/config").json()["desktop"] is True


def test_desktop_needs_a_token(tmp_path):
    with pytest.raises(ValueError):
        create_app(tmp_path, desktop=True)


def test_key_is_validated_kept_in_memory_and_never_returned(make, text_pdf, caplog):
    caplog.set_level(logging.DEBUG)
    c = make()
    r = c.put("/api/key", json={"api_key": KEY, "provider": "api"})
    assert r.status_code == 200 and KEY not in r.text
    assert KEY not in c.get("/api/config").text and c.get("/api/config").json()["has_key"]
    up = c.post("/api/jobs", files={"file": ("b.pdf", text_pdf.read_bytes())}).json()
    r = c.post(f"/api/jobs/{up['id']}/start", json={})  # no api_key in the request
    assert r.status_code == 200 and wait(c, up["id"])["state"] == "done"
    assert KEY not in caplog.text
    assert KEY not in json.dumps(c.get(f"/api/jobs/{up['id']}").json())
    assert not any(KEY in p.read_text(errors="ignore")
                   for p in c.app.state.store.root.rglob("*") if p.is_file())
    c.delete("/api/key")
    assert not c.get("/api/config").json()["has_key"]


def test_rejected_key_and_network_error_are_reported_separately(make):
    def reject(key, provider="api"):
        raise AuthError("bad")

    class Offline(FakeBackend):
        def complete(self, *a, **k):
            raise BackendError("offline")

    assert make(reject).put("/api/key", json={"api_key": KEY}).status_code == 401
    c = make(lambda key, provider="api": Offline())
    assert c.put("/api/key", json={"api_key": KEY}).status_code == 502
    assert not c.get("/api/config").json()["has_key"]  # not saved


def test_start_without_a_key_is_refused(make, text_pdf):
    c = make()
    up = c.post("/api/jobs", files={"file": ("b.pdf", text_pdf.read_bytes())}).json()
    assert c.post(f"/api/jobs/{up['id']}/start", json={}).status_code == 400


def test_original_file_name_is_kept_and_no_caps(make, text_pdf):
    c = make(max_upload_mb=0, max_pages=1)  # hosted limits are ignored
    r = c.post("/api/jobs", files={"file": ("化学之树.pdf", text_pdf.read_bytes())})
    assert r.status_code == 200 and r.json()["filename"] == "化学之树.pdf"
    c.put("/api/key", json={"api_key": KEY})
    assert c.post(f"/api/jobs/{r.json()['id']}/start", json={}).status_code == 200


def test_no_cleanup_and_stale_jobs_are_reset(tmp_path):
    store = JobStore(tmp_path / "data" / "jobs", keep_names=True)
    old = store.new("a.pdf", pages_total=1)
    store.write(old, state="running")
    import os
    for p in (store.root / old).iterdir():
        os.utime(p, (0, 0))  # decades old
    with TestClient(create_app(tmp_path / "data", desktop=True, token=TOKEN,
                               executor=ThreadPoolExecutor(1), retention_hours=0), headers=H) as c:
        j = c.get(f"/api/jobs/{old}").json()
        assert j["state"] == "paused"  # kept, and Start will not answer 409
        c.put("/api/key", json={"api_key": KEY})
        assert c.post(f"/api/jobs/{old}/start", json={}).status_code != 409


def test_cancel_pauses_and_start_continues(make, text_pdf):
    class Slow(FakeBackend):
        def complete(self, *a, **k):
            time.sleep(0.2)
            return super().complete(*a, **k)

    c = make(lambda key, provider="api": Slow())
    c.put("/api/key", json={"api_key": KEY})
    up = c.post("/api/jobs", files={"file": ("b.pdf", text_pdf.read_bytes())}).json()
    c.post(f"/api/jobs/{up['id']}/start", json={"auto_glossary": False})
    wait(c, up["id"], states=("running",))
    assert c.post(f"/api/jobs/{up['id']}/cancel").status_code == 200
    j = wait(c, up["id"])
    assert j["state"] == "paused", j
    assert c.post(f"/api/jobs/{up['id']}/cancel").status_code == 409
    assert c.post(f"/api/jobs/{up['id']}/start", json={"auto_glossary": False}).status_code == 200
    j = wait(c, up["id"])
    assert j["state"] == "done", j


def test_hosted_app_has_no_desktop_routes(tmp_path):
    c = TestClient(create_app(tmp_path / "d", executor=ThreadPoolExecutor(1)))
    assert c.put("/api/key", json={"api_key": KEY}).status_code in (404, 405)
    assert c.get("/api/config").json().get("desktop") is False


def whole_page(client, lang):
    """The page and the scripts it loads: the checks below are about everything the window runs."""
    page = client.get("/" + lang).text
    return page + "".join(client.get(src).text for src in re.findall(r'src="(/static/[^"]+)"', page))


def test_desktop_serves_its_own_page_and_hosted_keeps_the_old_one(make, tmp_path):
    c = make()
    page = whole_page(c, "en")
    assert "X-Booktrans-Token" in page and "AGPL" in page and "AGPL" in whole_page(c, "zh")
    hosted = TestClient(create_app(tmp_path / "h", executor=ThreadPoolExecutor(1)))
    assert "X-Booktrans-Token" not in whole_page(hosted, "en") and "Book Translator" in hosted.get("/en").text


def test_page_never_reads_or_stores_the_key(make):
    for lang in ("en", "zh"):
        page = whole_page(make(), lang)
        assert "localStorage" not in page and "sessionStorage" not in page
        assert "api_key: $" not in page  # keys travel via the shell or PUT /api/key only


def test_language_switch_hands_the_token_to_the_other_page(make):
    for lang in ("en", "zh"):
        js = whole_page(make(), lang)
        assert 'href += token ? "#token="' in js  # the token lives in page memory only, so the link must carry it


def test_job_list_is_newest_first_and_needs_the_token(make, text_pdf):
    c = make()
    a = c.post("/api/jobs", files={"file": ("a.pdf", text_pdf.read_bytes())}).json()["id"]
    time.sleep(0.02)
    b = c.post("/api/jobs", files={"file": ("b.pdf", text_pdf.read_bytes())}).json()["id"]
    assert [j["id"] for j in c.get("/api/jobs").json()] == [b, a]
    assert TestClient(c.app).get("/api/jobs").status_code == 401


# ---- spend guard ----

from tests.conftest import PricedBackend  # noqa: E402

ANY = ("needs_decision", "done", "failed", "paused")


def priced_client(make):
    c = make(lambda key, provider="api": PricedBackend())
    c.put("/api/key", json={"api_key": KEY})
    return c


def new_job(c, text_pdf, name="b.pdf"):
    return c.post("/api/jobs", files={"file": (name, text_pdf.read_bytes())}).json()["id"]


def start(c, job, **body):
    return c.post(f"/api/jobs/{job}/start", json={"auto_glossary": False, **body})


def test_desktop_defaults_to_ten_yuan_and_hosted_to_no_guard(make, tmp_path):
    cfg = make().get("/api/config").json()
    assert cfg["default_spend_limit"] == 10.0 and cfg["currency"] == "CNY"
    assert set(cfg["est_cny_per_page"]) >= {"api", "qwen", "qwen-intl", "deepseek"}
    hosted = TestClient(create_app(tmp_path / "h", executor=ThreadPoolExecutor(1)))
    assert hosted.get("/api/config").json()["default_spend_limit"] == 0


def test_stop_at_the_limit_then_raise_it_and_finish(make, text_pdf):
    c = priced_client(make)
    job = new_job(c, text_pdf)
    assert start(c, job, spend_limit=2.5).status_code == 200
    j = wait(c, job, states=ANY)
    assert j["state"] == "needs_decision"
    assert (j["spent_cny"], j["spend_limit"], j["done"], j["total"]) == (2.0, 2.5, 2, 3)
    assert j["est_rest_cny"] == 1.0  # about ¥1 per page, one page left
    assert start(c, job, spend_limit=2.0).status_code == 400  # not above what is spent
    assert start(c, job, spend_limit=-1).status_code == 400
    assert start(c, job, spend_limit=10).status_code == 200  # raise: carries on from the cache
    j = wait(c, job, states=ANY)
    assert j["state"] == "done" and j["spent_cny"] == 3.0 and not j["partial"]


def test_finish_with_the_translated_pages_spends_nothing(make, text_pdf):
    c = priced_client(make)
    job = new_job(c, text_pdf)
    start(c, job, spend_limit=2.5)
    assert wait(c, job, states=ANY)["state"] == "needs_decision"
    assert start(c, job, only_cached=True).status_code == 200
    j = wait(c, job, states=ANY)
    assert j["state"] == "done" and j["partial"] and j["spent_cny"] == 2.0
    from pypdf import PdfReader
    import io
    pdf = c.get(f"/api/jobs/{job}/download").content
    assert len(PdfReader(io.BytesIO(pdf)).pages) == 4


def test_stop_keeps_everything_and_start_can_carry_on_later(make, text_pdf):
    c = priced_client(make)
    job = new_job(c, text_pdf)
    start(c, job, spend_limit=2.5)
    wait(c, job, states=ANY)
    assert c.post(f"/api/jobs/{job}/cancel").json()["state"] == "paused"
    assert start(c, job, spend_limit=0).status_code == 200  # 0: no limit
    assert wait(c, job, states=ANY)["state"] == "done"


def test_the_default_limit_applies_when_the_request_names_none(make, text_pdf, monkeypatch):
    from booktrans import spend
    monkeypatch.setattr(spend, "DEFAULT_LIMIT_CNY", 2.5)
    c = priced_client(make)
    job = new_job(c, text_pdf)
    start(c, job)  # no spend_limit in the request
    assert wait(c, job, states=ANY)["state"] == "needs_decision"


def test_hosted_service_runs_without_a_limit_unless_asked(tmp_path, text_pdf):
    pool = ThreadPoolExecutor(1)
    c = TestClient(create_app(tmp_path / "h", executor=pool,
                              backend_factory=lambda key, provider="api": PricedBackend()))
    job = c.post("/api/jobs", files={"file": ("b.pdf", text_pdf.read_bytes())}).json()["id"]
    body = {"api_key": KEY, "auto_glossary": False}
    assert c.post(f"/api/jobs/{job}/start", json=body).status_code == 200
    end = time.time() + 20
    while c.get(f"/api/jobs/{job}").json()["state"] not in ("done", "failed") and time.time() < end:
        time.sleep(0.05)
    j = c.get(f"/api/jobs/{job}").json()
    assert j["state"] == "done" and j["spent_cny"] == 3.0  # counted, never stopped
    pool.shutdown(wait=True)


def test_the_key_never_appears_in_spend_fields(make, text_pdf):
    c = priced_client(make)
    job = new_job(c, text_pdf)
    start(c, job, spend_limit=2.5)
    j = wait(c, job, states=ANY)
    assert KEY not in json.dumps(j)


def test_unexpected_failure_is_logged_with_the_key_blanked(make, text_pdf, capsys):
    calls = []

    def factory(key, provider="api"):
        if calls:  # the key check at PUT /api/key goes first
            raise RuntimeError(f"boom with {key}")
        calls.append(1)
        return FakeBackend()

    c = make(factory)
    c.put("/api/key", json={"api_key": KEY})
    job = c.post("/api/jobs", files={"file": ("b.pdf", text_pdf.read_bytes())}).json()["id"]
    c.post(f"/api/jobs/{job}/start", json={})
    j = wait(c, job)
    err = capsys.readouterr().err
    assert j["state"] == "failed" and j["error_code"] == "unknown" and j["error_detail"] == "RuntimeError"
    assert "unexpected error" in j["error"] and KEY not in json.dumps(j)
    assert "Job failed" in err and "boom with ***" in err and KEY not in err


NEW_KEY = "sk-ant-replacement-9876543210zyxw"


def test_a_saved_key_can_be_replaced_corrected_and_cleared(make):
    seen = []

    def factory(key, provider="api"):
        seen.append(key)
        if key == "sk-ant-bad-key-0000000000":
            class Reject(FakeBackend):
                def complete(self, *a, **k):
                    raise AuthError("rejected")
            return Reject()
        return FakeBackend()

    c = make(factory)
    assert c.put("/api/key", json={"api_key": KEY}).status_code == 200
    # a bad replacement is refused and the old key stays in use
    assert c.put("/api/key", json={"api_key": "sk-ant-bad-key-0000000000", "provider": "qwen"}).status_code == 401
    assert c.get("/api/config").json()["provider"] == "api"
    assert c.get("/api/config").json()["has_key"]
    # an empty field never re-validates the old key under the new provider
    assert c.put("/api/key", json={"api_key": "  ", "provider": "qwen"}).status_code == 400
    assert c.get("/api/config").json()["provider"] == "api"
    # the corrected key replaces the old one, including the provider
    assert c.put("/api/key", json={"api_key": NEW_KEY, "provider": "api"}).status_code == 200
    assert NEW_KEY not in c.get("/api/config").text
    # clearing forgets it in the running session
    c.delete("/api/key")
    assert not c.get("/api/config").json()["has_key"]


def test_the_replacement_key_is_the_one_a_job_uses(make, text_pdf):
    used = []

    def factory(key, provider="api"):
        used.append(key)
        return FakeBackend()

    c = make(factory)
    up = c.post("/api/jobs", files={"file": ("b.pdf", text_pdf.read_bytes())}).json()
    c.put("/api/key", json={"api_key": KEY})
    c.put("/api/key", json={"api_key": NEW_KEY})
    c.post(f"/api/jobs/{up['id']}/start", json={"auto_glossary": False})
    wait(c, up["id"])
    assert used[-1] == NEW_KEY


@pytest.fixture
def mem_keyring(monkeypatch):
    import keyring
    from keyring.backend import KeyringBackend

    class Mem(KeyringBackend):
        priority = 1
        d = {}

        def get_password(self, s, u):
            return self.d.get((s, u))

        def set_password(self, s, u, p):
            self.d[(s, u)] = p

        def delete_password(self, s, u):
            self.d.pop((s, u), None)

    old = keyring.get_keyring()
    keyring.set_keyring(Mem())
    yield Mem
    keyring.set_keyring(old)


class FakeSide:
    """Stands in for the sidecar: answers PUT /api/key like the real one."""
    def __init__(self, client):
        self.http = client


def test_shell_replaces_keeps_old_on_failure_and_hints_only_the_last_four(make, mem_keyring):
    pytest.importorskip("keyring")
    from booktrans.desktop import shell

    def factory(key, provider="api"):
        class B(FakeBackend):
            def complete(self, *a, **k):
                if "bad" in key:
                    raise AuthError("rejected")
                return super().complete(*a, **k)
        return B()

    api = shell.Api(FakeSide(make(factory)))
    assert api.save_key("api", KEY)["ok"]
    assert shell.stored_key() == ("api", KEY)
    r = api.save_key("api", "sk-ant-bad-key-0000000000")
    assert not r["ok"] and r["status"] == 401
    assert shell.stored_key() == ("api", KEY)  # the working key was not overwritten
    assert not api.save_key("api", "   ")["ok"]
    assert api.save_key("api", NEW_KEY)["ok"] and shell.stored_key() == ("api", NEW_KEY)
    hint = api.has_key()
    assert hint["hint"] == "…" + NEW_KEY[-4:] and NEW_KEY not in json.dumps(hint)
    api.delete_key()
    assert api.has_key() == {"has_key": False, "provider": "", "hint": ""}
    assert not api._sidecar.http.get("/api/config").json()["has_key"]


def test_a_keyring_failure_is_reported_not_raised(make, mem_keyring, monkeypatch):
    from booktrans.desktop import shell
    import keyring

    def boom(*a):
        raise RuntimeError("locked")
    monkeypatch.setattr(keyring, "set_password", boom)
    r = shell.Api(FakeSide(make())).save_key("api", KEY)
    assert not r["ok"] and "could not be stored" in r["error"]


def test_the_page_offers_a_way_to_the_key_after_a_failure_and_shows_only_a_hint():
    from pathlib import Path
    static = Path(__file__).parent.parent / "booktrans/web/static"
    page = "".join((static / f).read_text(encoding="utf-8") for f in ("desktop.en.html", "desktop.js"))
    assert 'id="btn-changekey"' in page and 'show("btn-changekey", j.state === "failed")' in page
    assert "keyHint" in page and "k.slice(-4)" in page


def _chained(outer, inner):
    outer.__cause__ = inner
    return outer


@pytest.mark.parametrize("exc,code", [
    (__import__("booktrans.backends.base", fromlist=["x"]).AuthError("bad key"), "auth"),
    (__import__("booktrans.backends.base", fromlist=["x"]).BackendError(
        "Anthropic API error: Your credit balance is too low"), "quota"),
    (_chained(RuntimeError("x"), type("RateLimitError", (Exception,), {"status_code": 429})()), "rate_limit"),
    (_chained(RuntimeError("x"), type("APITimeoutError", (Exception,), {})("Request timed out.")), "timeout"),
    (_chained(RuntimeError("x"), type("APIConnectionError", (Exception,), {})("Connection error.")), "network"),
    (_chained(RuntimeError("x"), type("InternalServerError", (Exception,), {"status_code": 529})()), "server"),
    (OSError(28, "No space left on device"), "disk"),
    (MemoryError(), "memory"),
    (ValueError("Page range 90-99 is outside this book."), "input"),
    (__import__("booktrans.backends.base", fromlist=["x"]).BackendError("The model returned no answer."), "provider"),
    (KeyError("boom"), "unknown"),
])
def test_failures_are_classified_with_a_next_step(exc, code, capsys):
    from booktrans.web import jobs
    got, detail, text = jobs.failure_info(exc, KEY)
    assert got == code and detail and jobs.FAILURE_ADVICE[code] in text
    assert "Job failed" in capsys.readouterr().err


def test_failure_detail_never_holds_the_key(capsys):
    from booktrans.backends.base import BackendError
    from booktrans.web import jobs
    _, detail, text = jobs.failure_info(BackendError(f"API error: bad {KEY}"), KEY)
    assert KEY not in detail + text and "***" in detail
    assert KEY not in capsys.readouterr().err


# ---- model and OCR model pickers ----

def _recording(seen):
    def factory(key, provider="api", **chosen):
        seen.append((provider, chosen))
        return FakeBackend()
    return factory


def _book(c, text_pdf):
    c.put("/api/key", json={"api_key": "qwen-key-1234567890", "provider": "qwen"})
    return c.post("/api/jobs", files={"file": ("b.pdf", text_pdf.read_bytes())}).json()["id"]


def test_empty_model_means_the_provider_default(make, text_pdf):
    seen = []
    c = make(_recording(seen))
    job = _book(c, text_pdf)
    assert c.post(f"/api/jobs/{job}/start", json={"model": "  "}).status_code == 200
    assert wait(c, job)["state"] == "done"
    assert seen[-1] == ("qwen", {})  # nothing extra reaches the factory: the default applies


def test_custom_model_and_ocr_model_reach_make_backend(make, text_pdf, monkeypatch):
    got = {}
    import booktrans.backends as backends
    real = backends.make_backend

    def spy(name, model=None, usage=None, api_key=None, vision_model=None):
        got.update(name=name, model=model, vision_model=vision_model)
        return FakeBackend()
    monkeypatch.setattr(backends, "make_backend", spy)
    c = make(backend_factory_default())
    job = _book(c, text_pdf)
    r = c.post(f"/api/jobs/{job}/start", json={"model": " qwen-max ", "ocr": True, "ocr_model": "qwen-vl-plus"})
    assert r.status_code == 200 and wait(c, job)["state"] == "done"
    assert got == {"name": "qwen", "model": "qwen-max", "vision_model": "qwen-vl-plus"}
    assert c.get(f"/api/jobs/{job}").json()["price_approx"] is True
    monkeypatch.setattr(backends, "make_backend", real)


def backend_factory_default():
    from booktrans.web import jobs
    return jobs.default_backend


@pytest.mark.parametrize("bad", ["has space", "a;b", "x" * 101, "../etc", "-lead", "模型"])
def test_an_invalid_model_id_is_rejected_with_a_400(make, text_pdf, bad):
    c = make()
    job = _book(c, text_pdf)
    for field in ("model", "ocr_model"):
        r = c.post(f"/api/jobs/{job}/start", json={field: bad, "ocr": True})
        assert r.status_code == 400 and "model" in r.json()["detail"].lower()
    assert c.post(f"/api/jobs/{job}/glossary/draft", json={"model": bad}).status_code == 400
    assert c.get(f"/api/jobs/{job}").json()["state"] == "uploaded"


def test_ocr_model_is_refused_where_the_provider_cannot_read_pages(make, text_pdf):
    c = make()
    c.put("/api/key", json={"api_key": "ds-key-1234567890", "provider": "deepseek"})
    job = c.post("/api/jobs", files={"file": ("b.pdf", text_pdf.read_bytes())}).json()["id"]
    assert c.post(f"/api/jobs/{job}/start", json={"ocr_model": "x-vl"}).status_code == 400
    assert c.post(f"/api/jobs/{job}/start", json={"ocr": True}).status_code == 400
    # Anthropic reads pages with the one chosen model: a different OCR model is refused
    c.put("/api/key", json={"api_key": KEY, "provider": "api"})
    assert c.post(f"/api/jobs/{job}/start", json={"ocr_model": "claude-opus-5-5"}).status_code == 400
    assert c.post(f"/api/jobs/{job}/start", json={"model": "claude-opus-5-5", "ocr_model": "claude-opus-5-5"}).status_code == 200


def test_catalog_lists_defaults_first_and_deepseek_has_no_vision(make):
    models = make().get("/api/config").json()["models"]
    for name, c in models.items():
        assert not c["models"] or c["models"][0] == c["model"], name
        assert not c["vision_models"] or c["vision_models"][0] == c["vision"], name
    assert models["deepseek"]["vision"] is None and models["deepseek"]["vision_models"] == []
    assert models["api"]["ocr_shared"] is True and models["qwen"]["ocr_shared"] is False


def test_an_unknown_model_is_priced_at_the_provider_rate_and_marked_approximate():
    from booktrans import spend
    from booktrans.backends import catalog
    default = catalog()["qwen"]["model"]
    assert spend.price_approx("qwen", "") is False and spend.price_approx("qwen", default) is False
    assert spend.price_approx("qwen", "some-new-model") is True
    assert spend.price_approx("qwen", "", "qwen-vl-plus", ocr=False) is False  # OCR off: its model is unused
    assert spend.price_approx("qwen", "", "qwen-vl-plus", ocr=True) is True
    meter = spend.Meter(0)
    tokens = {"input_tokens": 1000, "output_tokens": 1000}
    assert meter.cost("qwen", "text", tokens) == (1000 * 0.8 + 1000 * 2.0) / 1e6  # the provider's rate, whatever the model


def test_hosted_requests_without_model_fields_still_work(tmp_path, text_pdf):
    pool = ThreadPoolExecutor(max_workers=1)
    c = TestClient(create_app(tmp_path / "data", executor=pool, backend_factory=lambda key, provider="api": FakeBackend()))
    job = c.post("/api/jobs", files={"file": ("b.pdf", text_pdf.read_bytes())}).json()["id"]
    r = c.post(f"/api/jobs/{job}/start", json={"api_key": KEY, "provider": "api"})
    assert r.status_code == 200 and wait(c, job)["state"] == "done"
    pool.shutdown(wait=True)


def test_model_choices_are_kept_per_provider_by_the_shell(tmp_path, monkeypatch):
    from booktrans.desktop import shell
    monkeypatch.setenv("BOOKTRANS_DATA", str(tmp_path))
    api = shell.Api(None)
    assert api.get_models() == {}
    assert api.set_models("qwen", "qwen-max", "qwen-vl-plus")["ok"]
    assert api.set_models("deepseek", "deepseek-reasoner", "")["ok"]
    assert api.get_models() == {"qwen": {"model": "qwen-max", "ocr_model": "qwen-vl-plus"},
                                "deepseek": {"model": "deepseek-reasoner", "ocr_model": ""}}
    assert api.set_models("qwen", "bad id!", "")["ok"] is False
    assert api.get_models()["qwen"]["model"] == "qwen-max"  # a refused value changes nothing
