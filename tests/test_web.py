import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from booktrans.backends.base import AuthError
from booktrans.web.app import create_app
from tests.conftest import FakeBackend

KEY = "sk-ant-test-1234567890abcdefghij"


@pytest.fixture
def make_client(tmp_path):
    pools = []

    def make(factory=lambda key: FakeBackend(), **kw):
        pool = ThreadPoolExecutor(max_workers=1)
        pools.append(pool)
        app = create_app(tmp_path / "data", executor=pool, backend_factory=factory, **kw)
        return TestClient(app)
    yield make
    for p in pools:
        p.shutdown(wait=True)


def upload(client, name, data):
    return client.post("/api/jobs", files={"file": (name, data)})


def wait(client, job_id, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["state"] in ("done", "failed"):
            return j
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_index_page_is_served(make_client):
    r = make_client().get("/")
    assert r.status_code == 200 and "Book Translator" in r.text


def test_upload_reports_page_count(make_client, text_pdf):
    r = upload(make_client(), "book.pdf", text_pdf.read_bytes())
    assert r.status_code == 200
    j = r.json()
    assert j["state"] == "uploaded" and j["pages_total"] == 3 and j["filename"] == "book.pdf"


def test_upload_rejects_other_types_and_big_files(make_client):
    assert upload(make_client(), "x.exe", b"MZ").status_code == 400
    assert upload(make_client(max_upload_mb=0), "a.txt", b"hello").status_code == 413
    assert upload(make_client(), "a.pdf", b"not a pdf").status_code == 400


def test_full_job_produces_bilingual_pdf(make_client, text_pdf):
    c = make_client()
    job = upload(c, "book.pdf", text_pdf.read_bytes()).json()
    r = c.post(f"/api/jobs/{job['id']}/start", json={"api_key": KEY})
    assert r.status_code == 200
    done = wait(c, job["id"])
    assert done["state"] == "done" and "usage" in done
    pdf = c.get(f"/api/jobs/{job['id']}/download")
    assert pdf.headers["content-type"] == "application/pdf"
    open_pages = PdfReader(__import__("io").BytesIO(pdf.content))
    assert len(open_pages.pages) == 6


def test_preview_translates_only_three_pages(make_client, tmp_path):
    c = make_client()
    text = "\n\n".join(f"Paragraph {i} " + "word " * 300 for i in range(40))
    job = upload(c, "long.txt", text.encode()).json()
    assert job["pages_total"] > 3
    c.post(f"/api/jobs/{job['id']}/start", json={"api_key": KEY, "preview": True})
    done = wait(c, job["id"])
    assert done["state"] == "done" and done["range"] == "1-3"
    pages = PdfReader(__import__("io").BytesIO(c.get(f"/api/jobs/{job['id']}/download").content)).pages
    assert len(pages) == 6


def test_start_validates_key_and_range(make_client, text_pdf):
    c = make_client()
    job = upload(c, "book.pdf", text_pdf.read_bytes()).json()
    url = f"/api/jobs/{job['id']}/start"
    assert c.post(url, json={"api_key": "hello"}).status_code == 400
    assert c.post(url, json={"api_key": KEY, "pages": "abc"}).status_code == 400
    assert c.post(url, json={"api_key": KEY, "pages": "50-60"}).status_code == 400


def test_page_limit(make_client, text_pdf):
    c = make_client(max_pages=2)
    job = upload(c, "book.pdf", text_pdf.read_bytes()).json()
    r = c.post(f"/api/jobs/{job['id']}/start", json={"api_key": KEY})
    assert r.status_code == 400 and "At most 2" in r.json()["detail"]


def test_rejected_key_fails_job_without_leaking_key(make_client, text_pdf, tmp_path):
    def factory(key):
        class Bad(FakeBackend):
            def complete(self, *a, **k):
                raise AuthError(f"The API key was rejected ({key})")
        return Bad()
    c = make_client(factory)
    job = upload(c, "book.pdf", text_pdf.read_bytes()).json()
    c.post(f"/api/jobs/{job['id']}/start", json={"api_key": KEY})
    done = wait(c, job["id"])
    assert done["state"] == "failed" and KEY not in done["error"] and "rejected" in done["error"]


def test_key_is_never_written_to_disk(make_client, text_pdf, tmp_path):
    c = make_client()
    job = upload(c, "book.pdf", text_pdf.read_bytes()).json()
    c.post(f"/api/jobs/{job['id']}/start", json={"api_key": KEY})
    wait(c, job["id"])
    for p in (tmp_path / "data").rglob("*"):
        if p.is_file():
            assert KEY.encode() not in p.read_bytes(), p


def test_unknown_and_malformed_ids_are_404(make_client):
    c = make_client()
    assert c.get("/api/jobs/" + "A" * 22).status_code == 404
    assert c.get("/api/jobs/..%2F..%2Fetc").status_code == 404
    assert c.get("/api/jobs/short").status_code == 404


def test_delete_removes_files(make_client, text_pdf, tmp_path):
    c = make_client()
    job = upload(c, "book.pdf", text_pdf.read_bytes()).json()
    assert c.delete(f"/api/jobs/{job['id']}").status_code == 200
    assert c.get(f"/api/jobs/{job['id']}").status_code == 404
    assert not any((tmp_path / "data" / "jobs").iterdir())


def test_cleanup_removes_old_jobs(make_client, text_pdf):
    import os
    c = make_client()
    job = upload(c, "book.pdf", text_pdf.read_bytes()).json()
    store = c.app.state.store
    old = time.time() - 48 * 3600
    for p in store.dir(job["id"]).iterdir():
        os.utime(p, (old, old))
    assert store.cleanup(24 * 3600) == 1
    assert c.get(f"/api/jobs/{job['id']}").status_code == 404
