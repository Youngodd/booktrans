import json
import logging
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


def test_desktop_serves_its_own_page_and_hosted_keeps_the_old_one(make, tmp_path):
    page = make().get("/").text
    assert "X-Booktrans-Token" in page and "AGPL" in page
    hosted = TestClient(create_app(tmp_path / "h", executor=ThreadPoolExecutor(1))).get("/").text
    assert "X-Booktrans-Token" not in hosted and "Book Translator" in hosted


def test_page_never_reads_or_stores_the_key(make):
    page = make().get("/").text
    assert "localStorage" not in page and "sessionStorage" not in page
    assert "api_key: $" not in page  # keys travel via the shell or PUT /api/key only


def test_job_list_is_newest_first_and_needs_the_token(make, text_pdf):
    c = make()
    a = c.post("/api/jobs", files={"file": ("a.pdf", text_pdf.read_bytes())}).json()["id"]
    time.sleep(0.02)
    b = c.post("/api/jobs", files={"file": ("b.pdf", text_pdf.read_bytes())}).json()["id"]
    assert [j["id"] for j in c.get("/api/jobs").json()] == [b, a]
    assert TestClient(c.app).get("/api/jobs").status_code == 401


@pytest.fixture
def clean_proxy_env(monkeypatch):
    for n in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
        monkeypatch.delenv(n, raising=False)
    yield
    # monkeypatch undoes anything the endpoint set only for names it knew about; clear the rest
    import os
    for n in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
        os.environ.pop(n, None)


def test_proxy_is_applied_hidden_and_clearable(make, clean_proxy_env):
    import os
    import httpx
    c = make()
    r = c.put("/api/proxy", json={"url": "http://me:s3cret@127.0.0.1:7890"})
    assert r.status_code == 200 and r.json()["proxy"] == "127.0.0.1:7890"
    assert "s3cret" not in r.text and "s3cret" not in c.get("/api/config").text
    assert c.get("/api/config").json()["proxy"] == "127.0.0.1:7890"
    assert os.environ["HTTPS_PROXY"] == "http://me:s3cret@127.0.0.1:7890"
    assert httpx.Client()._mounts  # the provider SDKs build their clients like this
    assert c.put("/api/proxy", json={"url": ""}).json() == {"proxy": ""}
    assert "HTTPS_PROXY" not in os.environ


def test_proxy_address_is_validated_and_needs_the_token(make, clean_proxy_env):
    c = make()
    for bad in ("127.0.0.1:7890", "ftp://h:1", "http://", "not a url"):
        assert c.put("/api/proxy", json={"url": bad}).status_code == 400, bad
    assert TestClient(c.app).put("/api/proxy", json={"url": "http://h:1"}).status_code == 401


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
