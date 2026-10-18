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
    assert wait(c, up["id"])["state"] == "paused"
    assert c.post(f"/api/jobs/{up['id']}/cancel").status_code == 409
    assert c.post(f"/api/jobs/{up['id']}/start", json={"auto_glossary": False}).status_code == 200
    assert wait(c, up["id"])["state"] == "done"


def test_hosted_app_has_no_desktop_routes(tmp_path):
    c = TestClient(create_app(tmp_path / "d", executor=ThreadPoolExecutor(1)))
    assert c.put("/api/key", json={"api_key": KEY}).status_code in (404, 405)
    assert c.get("/api/config").json().get("desktop") is False
