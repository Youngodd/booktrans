"""Edge cases of the web service (docs/edge-case-test-plan.md, area 6): hostile uploads, wrong states, odd
settings, jobs side by side. The service is untrusted-input facing, so these look for 500s and for files
written or read outside a job's folder."""
import io
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor

import fitz
import pytest
from fastapi.testclient import TestClient

from booktrans.web.app import create_app
from tests.conftest import FakeBackend

KEY = "sk-ant-test-1234567890abcdefghij"
TEXT = ("Paragraph one of a short book. " * 8 + "\n\n") * 4


@pytest.fixture
def make(tmp_path):
    pools = []

    def build(factory=lambda key, provider="api", **kw: FakeBackend(), workers=1, **kw):
        pool = ThreadPoolExecutor(max_workers=workers)
        pools.append(pool)
        return TestClient(create_app(tmp_path / "data", executor=pool, backend_factory=factory, **kw))
    yield build
    for p in pools:
        p.shutdown(wait=True)


def upload(c, name, data):
    return c.post("/api/jobs", files={"file": (name, data)})


def wait(c, job_id, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        j = c.get(f"/api/jobs/{job_id}").json()
        if j["state"] in ("done", "failed"):
            return j
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def start(c, job_id, **body):
    return c.post(f"/api/jobs/{job_id}/start", json={"api_key": KEY, **body})


def everything_under(root):
    return {p for p in root.rglob("*")}


# ---------------------------------------------------------------- uploads

@pytest.mark.parametrize("name", ["", "noextension", "book.exe", "book.pdf.exe", "book.docx.zip", ".pdf.", "book.doc",
                                  "book.rtf", "book.mobi", "book.pdf ", "x.html"])
def test_a_file_of_an_unsupported_type_is_refused(make, name):
    r = upload(make(), name, b"data")
    assert r.status_code == (422 if name == "" else 400)  # no file name at all is not a file part
    if r.status_code == 400:
        assert "Upload a PDF" in r.json()["detail"]


@pytest.mark.parametrize("name", ["B.PDF", "b.Epub", "c.DOCX", "d.Md", "e.TXT", "f.markdown"])
def test_the_extension_is_matched_whatever_its_case(make, name):
    # a body that is not a book in that format: the answer is 400 (not readable) or 200, never a server error
    r = upload(make(), name, b"Some plain text, long enough to be read as a short text file.")
    assert r.status_code in (200, 400)


@pytest.mark.parametrize("name", ["empty.pdf", "empty.docx", "empty.epub", "empty.txt", "empty.md"])
def test_an_empty_file_is_refused_or_has_no_pages_never_a_server_error(make, name):
    r = upload(make(), name, b"")
    assert r.status_code == 400 or (r.status_code == 200 and r.json()["pages_total"] == 0)


@pytest.mark.parametrize("name,body", [("a.pdf", b"%PDF-1.4 truncated"), ("a.docx", b"not a zip"),
                                       ("a.epub", b"PK\x03\x04 broken"), ("a.docx", b"\x00" * 100),
                                       ("a.epub", b"plain text")])
def test_a_damaged_file_is_a_400_and_leaves_no_job_behind(make, tmp_path, name, body):
    c = make()
    r = upload(c, name, body)
    assert r.status_code == 400 and ("could not be read" in r.json()["detail"] or "not a readable" in r.json()["detail"])
    assert not any((tmp_path / "data" / "jobs").iterdir())


def test_a_password_protected_pdf_is_refused_with_the_reason(make, tmp_path):
    d = fitz.open()
    d.new_page().insert_text((72, 100), "A page of text in a locked PDF file, long enough.")
    buf = tmp_path / "locked.pdf"
    d.save(str(buf), encryption=fitz.PDF_ENCRYPT_RC4_128, owner_pw="o", user_pw="u")
    r = upload(make(), "locked.pdf", buf.read_bytes())
    assert r.status_code == 400 and "password" in r.json()["detail"].lower()


def test_a_pdf_locked_only_against_copying_is_accepted(make, tmp_path):
    d = fitz.open()
    d.new_page().insert_text((72, 100), "A page of text in a restricted PDF file, long enough.")
    p = tmp_path / "owner.pdf"
    d.save(str(p), encryption=fitz.PDF_ENCRYPT_RC4_128, owner_pw="o", user_pw="")
    r = upload(make(), "owner.pdf", p.read_bytes())
    assert r.status_code == 200 and r.json()["pages_total"] == 1


@pytest.mark.parametrize("name", ["../../evil.md", "..\\..\\evil.md", "/etc/cron.d/evil.md", "a/b/c.md", "x\x00y.md",
                                  "con.md", "..", "....md", "a" * 400 + ".md", "名前 with spaces 😀.md",
                                  'quote".md', "line\r\nbreak.md"])
def test_a_hostile_file_name_cannot_write_outside_the_job_folder(make, tmp_path, name):
    root = tmp_path / "data"
    before = everything_under(tmp_path)
    c = make()
    r = upload(c, name, TEXT.encode())
    assert r.status_code in (200, 400)
    new = everything_under(tmp_path) - before
    assert all(root in p.parents or p == root for p in new), new  # nothing outside the data folder
    if r.status_code == 200:
        job = r.json()
        assert "/" not in job["filename"] and "\\" not in job["filename"] and "\n" not in job["filename"]
        assert start(c, job["id"]).status_code == 200
        done = wait(c, job["id"])
        assert done["state"] == "done"
        d = c.get(f"/api/jobs/{job['id']}/download")
        assert d.status_code == 200 and "\n" not in d.headers["content-disposition"]


def test_too_big_an_upload_is_refused_and_removed(make, tmp_path):
    c = make(max_upload_mb=1)
    r = upload(c, "big.txt", b"x" * (2 << 20))
    assert r.status_code == 413
    assert not any((tmp_path / "data" / "jobs").iterdir())


def test_an_upload_just_under_the_limit_is_accepted(make):
    c = make(max_upload_mb=1)
    r = upload(c, "ok.txt", (b"word " * 100 + b"\n\n") * 1500)  # about 0.8 MB
    assert r.status_code == 200


def test_a_request_with_no_file_is_a_422_not_a_crash(make):
    assert make().post("/api/jobs").status_code == 422


# ---------------------------------------------------------------- settings

@pytest.fixture
def job_of(make):
    c = make()
    return c, upload(c, "book.md", ("# T\n\n" + TEXT).encode()).json()["id"]


@pytest.mark.parametrize("body", [{"output_format": "mobi"}, {"output_format": ""}, {"output_format": "PDF"},
                                  {"output_mode": "both"}, {"source": "xx"}, {"target": "xx"}, {"target": ""},
                                  {"pages": "abc"}, {"pages": "0"}, {"pages": "9-1"}, {"pages": "99"},
                                  {"pages": "5-"}, {"provider": "nope"}, {"api_key": ""}, {"api_key": "   "},
                                  {"api_key": "short"}, {"model": "bad model!"}, {"model": "x" * 200},
                                  {"spend_limit": -1}, {"spend_limit": "abc"}, {"email": "nope"}])
def test_a_bad_setting_is_a_400_or_422_and_starts_nothing(job_of, body):
    c, job_id = job_of
    r = c.post(f"/api/jobs/{job_id}/start", json={"api_key": KEY, **body})
    assert r.status_code in (400, 422), (body, r.status_code, r.text)
    assert c.get(f"/api/jobs/{job_id}").json()["state"] == "uploaded"


@pytest.mark.parametrize("fmt", ["pdf", "epub", "docx", "md"])
@pytest.mark.parametrize("mode", ["bilingual", "target-only"])
def test_every_format_and_mode_gives_a_download_of_the_right_kind(make, fmt, mode):
    c = make()
    job = upload(c, "book.md", ("# T\n\n" + TEXT).encode()).json()
    assert start(c, job["id"], output_format=fmt, output_mode=mode).status_code == 200
    assert wait(c, job["id"])["state"] == "done"
    d = c.get(f"/api/jobs/{job['id']}/download")
    assert d.status_code == 200 and d.headers["content-disposition"].lower().count("filename") >= 1
    head = d.content[:4]
    assert head == (b"%PDF" if fmt == "pdf" else b"PK\x03\x04" if fmt in ("epub", "docx") else head)
    if fmt == "md":
        assert "译" in d.content.decode("utf-8")


def test_unicode_and_quote_file_names_are_downloaded_under_a_safe_header(make):
    c = make()
    job = upload(c, '我的书 "第一章".md', ("# T\n\n" + TEXT).encode()).json()
    start(c, job["id"], output_format="docx")
    assert wait(c, job["id"])["state"] == "done"
    d = c.get(f"/api/jobs/{job['id']}/download")
    disp = d.headers["content-disposition"]
    assert disp.isascii() and "\n" not in disp and "docx" in disp


def test_a_book_with_pictures_written_as_markdown_comes_as_a_zip(make, tmp_path):
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 30, 30), False)
    pix.set_rect(pix.irect, (10, 120, 200))
    pix.save(str(tmp_path / "pic.png"))
    import docx
    d = docx.Document()
    d.add_paragraph("A paragraph before the picture.")
    d.add_picture(str(tmp_path / "pic.png"))
    d.save(str(tmp_path / "w.docx"))
    c = make()
    job = upload(c, "w.docx", (tmp_path / "w.docx").read_bytes()).json()
    start(c, job["id"], output_format="md")
    assert wait(c, job["id"])["state"] == "done"
    got = c.get(f"/api/jobs/{job['id']}/download")
    names = zipfile.ZipFile(io.BytesIO(got.content)).namelist()
    assert any(n.endswith(".md") for n in names) and any("_assets/" in n for n in names)


# ---------------------------------------------------------------- states

def blocking_backend():
    gate, entered = threading.Event(), threading.Event()

    class Slow(FakeBackend):
        def complete(self, system, user, max_tokens=4096):
            entered.set()
            gate.wait(20)
            return super().complete(system, user, max_tokens)
    return Slow, gate, entered


def test_wrong_state_calls_get_409_not_a_crash(make):
    Slow, gate, entered = blocking_backend()
    c = make(lambda key, provider="api", **kw: Slow())
    job = upload(c, "book.md", ("# T\n\n" + TEXT).encode()).json()
    jid = job["id"]
    assert c.get(f"/api/jobs/{jid}/download").status_code == 409  # not started
    assert start(c, jid).status_code == 200
    assert entered.wait(10)
    try:
        assert start(c, jid).status_code == 409  # already running
        assert c.get(f"/api/jobs/{jid}/download").status_code == 409
        assert c.delete(f"/api/jobs/{jid}").status_code == 409
        assert c.post(f"/api/jobs/{jid}/glossary/import", json={"text": "A=b"}).status_code in (409, 400)
        assert c.get(f"/api/jobs/{jid}/glossary/download").status_code in (404, 409)
    finally:
        gate.set()
    assert wait(c, jid)["state"] == "done"
    assert c.delete(f"/api/jobs/{jid}").status_code == 200
    assert c.delete(f"/api/jobs/{jid}").status_code == 404  # twice
    assert c.get(f"/api/jobs/{jid}/download").status_code == 404


@pytest.mark.parametrize("path", ["", "/start", "/download", "/glossary/download", "/glossary/draft", "/result"])
@pytest.mark.parametrize("job_id", ["A" * 22, "..", "..%2F..%2Fetc%2Fpasswd", "a" * 5000, "%00", "x y"])
def test_an_unknown_or_hostile_job_id_is_a_404_or_405_everywhere(make, path, job_id):
    c = make()
    for call in (c.get, c.post, c.delete):
        r = call(f"/api/jobs/{job_id}{path}")
        assert r.status_code in (404, 405, 422, 400), (call.__name__, path, job_id, r.status_code)


def test_a_failing_provider_fails_the_job_cleanly_and_a_retry_works(make):
    state = {"down": True}

    class Flaky(FakeBackend):
        def complete(self, system, user, max_tokens=4096):
            if state["down"]:
                from booktrans.backends.base import AuthError
                raise AuthError("rejected")
            return super().complete(system, user, max_tokens)
    c = make(lambda key, provider="api", **kw: Flaky())
    job = upload(c, "book.md", ("# T\n\n" + TEXT).encode()).json()
    start(c, job["id"])
    assert wait(c, job["id"])["state"] == "failed"
    state["down"] = False
    assert start(c, job["id"]).status_code == 200
    assert wait(c, job["id"])["state"] == "done"


def test_a_backend_that_raises_something_unexpected_fails_the_job_without_leaking_the_key(make):
    class Odd(FakeBackend):
        def complete(self, system, user, max_tokens=4096):
            raise RuntimeError(f"internal failure with {KEY} inside")
    c = make(lambda key, provider="api", **kw: Odd())
    job = upload(c, "book.md", ("# T\n\n" + TEXT).encode()).json()
    start(c, job["id"])
    done = wait(c, job["id"])
    assert done["state"] == "failed" and KEY not in str(done)


def test_several_jobs_at_once_each_get_their_own_result(make):
    c = make(workers=3)
    ids = []
    for n in range(5):
        text = f"# Book number {n}\n\n" + TEXT.replace("Paragraph", f"Book{n}Paragraph")
        ids.append(upload(c, f"b{n}.md", text.encode()).json()["id"])
    for jid in ids:
        assert start(c, jid, output_format="md").status_code == 200
    for n, jid in enumerate(ids):
        assert wait(c, jid)["state"] == "done"
        text = c.get(f"/api/jobs/{jid}/download").content.decode("utf-8")
        assert f"Book{n}Paragraph" in text and all(f"Book{m}Paragraph" not in text for m in range(5) if m != n)


def test_a_job_cannot_be_read_with_another_jobs_id_parts(make):
    c = make()
    a = upload(c, "a.md", ("# A\n\n" + TEXT).encode()).json()["id"]
    b = upload(c, "b.md", ("# B\n\n" + TEXT).encode()).json()["id"]
    assert a != b and a[:10] != b[:10]
    assert c.get(f"/api/jobs/{a[:21]}").status_code == 404


def test_the_recommendation_comes_with_every_kind_of_upload(make):
    c = make()
    for name, body in [("a.md", b"# T\n\nHello there, a short book to read."), ("a.txt", b"Hello there, a short book to read.")]:
        job = upload(c, name, body).json()
        assert job["recommended"]["settings"]["output_mode"] == "bilingual"
        assert all(set(v) == {"en", "zh"} for v in job["recommended"]["reasons"].values())


def test_a_pdf_of_many_pages_is_counted_and_a_range_is_enforced(make, tmp_path):
    d = fitz.open()
    for i in range(60):
        d.new_page().insert_text((72, 100), f"Page {i} of a long book, with some text on it.")
    p = tmp_path / "long.pdf"
    d.save(str(p))
    c = make(max_pages=50)
    job = upload(c, "long.pdf", p.read_bytes()).json()
    assert job["pages_total"] == 60
    assert start(c, job["id"]).status_code == 400  # more pages than allowed
    assert start(c, job["id"], pages="1-50").status_code == 200
    assert wait(c, job["id"])["state"] == "done"


# ---------------------------------------------------------------- audit round 2

def test_job_state_written_from_many_threads_at_once_never_fails_or_corrupts(tmp_path):
    from booktrans.web.jobs import JobStore
    store = JobStore(tmp_path)
    job_id = store.new("a.pdf")
    errors = []

    def writer(n):
        try:
            for i in range(40):
                store.write(job_id, **{f"field{n}": i, "done": i})
        except BaseException as e:
            errors.append(e)
    threads = [threading.Thread(target=writer, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == [] and store.read(job_id)["state"] == "uploaded"
    assert not list((tmp_path / job_id).glob("*.tmp"))
