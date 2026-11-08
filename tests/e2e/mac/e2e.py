"""E2E steps 3-6 against the real sidecar (fake backend shim). usage: e2e.py REPO SCRATCH"""
import json, os, re, subprocess, sys, time, shutil, signal
from pathlib import Path
import fitz, httpx

REPO, S = Path(sys.argv[1]), Path(sys.argv[2])
TOOLS, DATA, RUN = Path(__file__).resolve().parent, S / "testdata", S / "run"
DATA.mkdir(parents=True, exist_ok=True); RUN.mkdir(parents=True, exist_ok=True)
PY = str(REPO / ".venv/bin/python")
RESULTS, PROCS = [], []

def rec(id_, status, note):
    RESULTS.append((id_, status, note)); print(f"[{status}] {id_}: {note}", flush=True)

def check(id_, fn):
    try:
        note = fn(); rec(id_, "pass", note or "ok")
    except AssertionError as e:
        rec(id_, "FAIL", f"{e}"[:500])
    except Exception as e:
        rec(id_, "FAIL", f"{type(e).__name__}: {e}"[:500])

def env_for(data, **extra):
    e = {**os.environ, "PYTHONPATH": str(REPO), "BOOKTRANS_DATA": str(data), "BOOKTRANS_FAKE_BACKEND": "1",
         "PYTHONIOENCODING": "utf-8", "FAKEKR_FILE": str(RUN / "kr.json"),
         "PYTHON_KEYRING_BACKEND": "fakekr.FileKR", "BOOKTRANS_SHIM_FAIL_FILE": str(RUN / "fail.flag")}
    e["PYTHONPATH"] += os.pathsep + str(TOOLS)
    e.update({k: str(v) for k, v in extra.items()})
    return e

class Side:
    def __init__(self, data, **extra):
        self.data = Path(data); self.extra = extra
    def start(self):
        self.ready = RUN / f"ready-{time.time_ns()}"
        self.out = open(RUN / "sidecar.stdout", "a")
        self.proc = subprocess.Popen([PY, str(TOOLS / "shim.py"), "--ready-file", str(self.ready)],
                                     cwd=str(REPO), env=env_for(self.data, **self.extra), stdout=self.out, stderr=subprocess.STDOUT)
        PROCS.append(self.proc)
        end = time.time() + 60
        while not self.ready.exists():
            assert time.time() < end and self.proc.poll() is None, "sidecar did not start"
            time.sleep(0.1)
        m = re.search(r"port=(\d+) token=(\S+)", self.ready.read_text())
        self.c = httpx.Client(base_url=f"http://127.0.0.1:{m[1]}", headers={"X-Booktrans-Token": m[2]}, timeout=60, trust_env=False)
        for _ in range(100):
            try: self.c.get("/healthz"); break
            except httpx.TransportError: time.sleep(0.1)
        return self
    def kill(self, sig=signal.SIGKILL):
        self.proc.send_signal(sig); self.proc.wait()
    def stop(self):
        if self.proc.poll() is None: self.proc.terminate(); self.proc.wait(10)

def make_pdf(path, pages, tag="Page"):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    d = fitz.open()
    for n in range(pages):
        p = d.new_page()
        p.insert_text((72, 100), f"{tag} heading {n+1}", fontsize=20)
        p.insert_textbox(fitz.Rect(72, 130, 500, 300), f"Body paragraph {n+1} of the book, long enough to wrap onto several lines of the page. Dr Alpha Zeta met Professor Beta Omega.", fontsize=11)
    d.save(path)

def make_epub(path):
    from ebooklib import epub
    b = epub.EpubBook(); b.set_identifier("x1"); b.set_title("Test"); b.set_language("en")
    chs = []
    for i in range(3):
        c = epub.EpubHtml(title=f"C{i}", file_name=f"c{i}.xhtml", lang="en")
        c.content = f"<h1>Chapter {i}</h1><p>This is paragraph one of chapter {i}, with enough words to be a paragraph.</p><p>Second paragraph of chapter {i} here.</p>"
        b.add_item(c); chs.append(c)
    b.toc = chs; b.add_item(epub.EpubNcx()); b.add_item(epub.EpubNav()); b.spine = ["nav"] + chs
    epub.write_epub(str(path), b)

def upload(side, path):
    r = side.c.post("/api/jobs", files={"file": (Path(path).name, Path(path).read_bytes())})
    assert r.status_code == 200, r.text
    return r.json()

def key(side, k="sk-test-0000"):
    r = side.c.put("/api/key", json={"api_key": k, "provider": "api"}); assert r.status_code == 200, r.text

def start(side, jid, **kw):
    body = {"auto_glossary": False, "spend_limit": 0, **kw}
    return side.c.post(f"/api/jobs/{jid}/start", json=body)

def wait(side, jid, states=("done", "failed", "paused", "needs_decision"), timeout=180):
    end = time.time() + timeout
    while time.time() < end:
        j = side.c.get(f"/api/jobs/{jid}").json()
        if j["state"] in states: return j
        time.sleep(0.2)
    raise AssertionError(f"timeout waiting, last={j}")

def pdf_of(side, jid):
    r = side.c.get(f"/api/jobs/{jid}/download"); assert r.status_code == 200, r.text
    return fitz.open(stream=r.content, filetype="pdf"), r

def ncalls(): 
    f = RUN / "calls.log"
    return len(f.read_text(encoding="utf-8").splitlines()) if f.exists() else 0

def main():
    for f in RUN.glob("*"): shutil.rmtree(f) if f.is_dir() else f.unlink()
    pdf12, epub, txt = DATA / "book12.pdf", DATA / "book.epub", DATA / "book.txt"
    zh = DATA / "测试" / "书籍" / "化学之树.pdf"
    make_pdf(pdf12, 12); make_epub(epub); make_pdf(zh, 4)
    txt.write_text("\n\n".join(f"Paragraph {i}. This is a plain text paragraph for the test." for i in range(8)), encoding="utf-8")
    calls = RUN / "calls.log"
    side = Side(RUN / "data", BOOKTRANS_SHIM_CALLS=calls).start()
    try:
        # ---- step 4: translation
        T = {}
        def t_pdf():
            j = upload(side, pdf12); key(side); T["pdf"] = j["id"]
            assert j["pages_total"] == 12, j
            assert start(side, j["id"]).status_code == 200
            j = wait(side, j["id"]); assert j["state"] == "done", j
            doc, r = pdf_of(side, j["id"])
            txt0, txt1 = doc[0].get_text(), doc[1].get_text()
            assert doc.page_count == 24, doc.page_count
            assert "Page heading 1" in txt0 and "译" not in txt0 and "译" in txt1, (txt0[:80], txt1[:80])
            T["calls_full"] = ncalls()
            return f"12 pages -> {doc.page_count} pages, p1 original, p2 Chinese ({txt1.strip()[:30]!r}), calls={ncalls()}"
        check("T2-pdf (C16)", t_pdf)
        def t_epub():
            j = upload(side, epub); assert start(side, j["id"]).status_code == 200
            j = wait(side, j["id"]); assert j["state"] == "done", j
            doc, _ = pdf_of(side, j["id"]); assert "译" in "".join(p.get_text() for p in doc)
            return f"epub done, {doc.page_count} pages, Chinese present"
        check("T2-epub (C18)", t_epub)
        def t_txt():
            j = upload(side, txt); assert start(side, j["id"]).status_code == 200
            j = wait(side, j["id"]); assert j["state"] == "done", j
            doc, _ = pdf_of(side, j["id"]); assert "译" in "".join(p.get_text() for p in doc)
            return f"txt done, {doc.page_count} pages, Chinese present"
        check("T2-txt (C18)", t_txt)
        def t_range():
            j = upload(side, pdf12); r = start(side, j["id"], pages="3-5"); assert r.status_code == 200, r.text
            j = wait(side, j["id"]); assert j["state"] == "done", j
            doc, _ = pdf_of(side, j["id"]); assert doc.page_count == 6, doc.page_count
            assert "heading 3" in doc[0].get_text(), doc[0].get_text()[:60]
            bad = start(side, upload(side, pdf12)["id"], pages="50-60"); assert bad.status_code == 400, bad.text
            return f"range 3-5 -> {doc.page_count} pages starting at page 3; range 50-60 rejected 400"
        check("C16-range", t_range)
        def t_preview():
            j = upload(side, pdf12); r = start(side, j["id"], preview=True); assert r.status_code == 200, r.text
            j = wait(side, j["id"]); assert j["state"] == "done", j
            doc, _ = pdf_of(side, j["id"]); assert doc.page_count == 6, doc.page_count
            return f"preview -> {doc.page_count} pages (3 pages x original+Chinese), range={j.get('range')}"
        check("C16-preview", t_preview)
        def t_gloss():
            j = upload(side, pdf12); jid = j["id"]
            r = side.c.post(f"/api/jobs/{jid}/glossary/draft", json={"pages": "1-3"}); assert r.status_code == 200, r.text
            end = time.time() + 60
            while time.time() < end and side.c.get(f"/api/jobs/{jid}/glossary").json()["state"] not in ("ready", "failed"): time.sleep(0.2)
            g = side.c.get(f"/api/jobs/{jid}/glossary").json()
            assert g["state"] == "ready", g
            r = side.c.put(f"/api/jobs/{jid}/glossary", json={"entries": {"Alpha Zeta": "阿尔法泽塔XYZ"}}); assert r.status_code == 200, r.text
            calls.write_text("")
            assert start(side, jid, pages="1-3", auto_glossary=False).status_code == 200
            j = wait(side, jid); assert j["state"] == "done", j
            used = "阿尔法泽塔XYZ" in calls.read_text(encoding="utf-8")
            assert used, "edited rendering never reached a translation call"
            return f"draft entries={len(g['entries'])}; edited rendering '阿尔法泽塔XYZ' present in the translation prompts (n calls={ncalls()})"
        check("C17 glossary review", t_gloss)
        def t_zh():
            j = upload(side, zh); assert j["filename"] == "化学之树.pdf", j["filename"]
            assert start(side, j["id"]).status_code == 200
            j = wait(side, j["id"]); assert j["state"] == "done", j
            doc, r = pdf_of(side, j["id"])
            cd = r.headers.get("content-disposition", "")
            from urllib.parse import unquote
            assert "化学之树_bilingual.pdf" in unquote(cd), cd
            return f"filename kept, download name: {unquote(cd)[:90]}; data dir path has Chinese: {(RUN/'data')}"
        check("C20 Chinese name (C1/C2)", t_zh)
        def t_cancel():
            side.stop()
            global side2
            s2 = Side(RUN / "data2", BOOKTRANS_SHIM_CALLS=calls, BOOKTRANS_SHIM_DELAY=0.25).start(); T["s2"] = s2
            calls.write_text("")
            j = upload(s2, pdf12); key(s2); jid = j["id"]; T["cj"] = jid
            assert start(s2, jid).status_code == 200
            while ncalls() < 4: time.sleep(0.1)
            r = s2.c.post(f"/api/jobs/{jid}/cancel"); assert r.status_code == 200, r.text
            j = wait(s2, jid, ("paused", "done", "failed")); assert j["state"] == "paused", j
            n1 = ncalls(); time.sleep(1); assert ncalls() == n1, "calls continued after pause"
            assert start(s2, jid).status_code == 200
            j = wait(s2, jid, ("done", "failed")); assert j["state"] == "done", j
            n2 = ncalls(); full = T["calls_full"]
            assert n2 <= full + 2, f"redid finished pages: {n2} calls vs {full} for a clean run"
            return f"paused after {n1} calls, no calls while paused; continue done, total calls {n2} vs clean run {full} (redo<=2)"
        check("T4 cancel/continue (C21)", t_cancel)
        def t_killmid():
            s2 = T["s2"]; data = s2.data
            calls.write_text("")
            j = upload(s2, pdf12); jid = j["id"]
            assert start(s2, jid).status_code == 200
            while ncalls() < 4: time.sleep(0.1)
            s2.kill()  # hard kill, as a crash
            s3 = Side(data, BOOKTRANS_SHIM_CALLS=calls).start(); T["s3"] = s3
            jobs = s3.c.get("/api/jobs").json(); mine = [x for x in jobs if x["id"] == jid][0]
            assert mine["state"] == "paused", mine["state"]
            key(s3); r = start(s3, jid); assert r.status_code == 200, f"{r.status_code} {r.text}"
            j = wait(s3, jid, ("done", "failed")); assert j["state"] == "done", j
            return f"after kill -9 mid-run and relaunch: job shown paused, Continue -> 200, finished done"
        check("T5 kill mid-run (C22)", t_killmid)
        def t_delete():
            s3 = T["s3"]; jid = T["cj"]
            d = s3.data / "jobs" / jid
            assert d.exists(), d
            r = s3.c.delete(f"/api/jobs/{jid}"); assert r.status_code == 200, r.text
            assert not d.exists() and s3.c.get(f"/api/jobs/{jid}").status_code == 404
            return "job folder removed, GET -> 404"
        check("T6 delete (C26)", t_delete)
        # ---- step 5: spend guard
        def t_spend():
            s3 = T["s3"]
            def fresh(): return upload(s3, pdf12)["id"]
            jid = fresh(); assert start(s3, jid, spend_limit=3).status_code == 200
            j = wait(s3, jid); assert j["state"] == "needs_decision", j
            spent, rest = j["spent_cny"], j.get("est_rest_cny")
            assert 2.5 <= spent <= 3.0, spent
            msg = [f"limit 3: needs_decision, spent={spent}, est_rest={rest}"]
            # raise
            assert start(s3, jid, spend_limit=100).status_code == 200
            j = wait(s3, jid); assert j["state"] == "done" and not j.get("partial"), j
            doc, _ = pdf_of(s3, jid); assert doc.page_count == 24, doc.page_count
            msg.append(f"raise: done, 24 pages, spent={j['spent_cny']}")
            # finish partial
            jid2 = fresh(); start(s3, jid2, spend_limit=3); assert wait(s3, jid2)["state"] == "needs_decision"
            assert start(s3, jid2, only_cached=True, spend_limit=3).status_code == 200
            j = wait(s3, jid2); assert j["state"] == "done" and j.get("partial") is True, j
            doc, _ = pdf_of(s3, jid2); msg.append(f"finish-partial: done, partial=True, {doc.page_count} pages, spent={j['spent_cny']}")
            # stop
            jid3 = fresh(); start(s3, jid3, spend_limit=3); assert wait(s3, jid3)["state"] == "needs_decision"
            r = s3.c.post(f"/api/jobs/{jid3}/cancel"); assert r.status_code == 200 and r.json()["state"] == "paused", r.text
            msg.append("stop: paused")
            # start again with a limit already spent is refused
            r = start(s3, jid3, spend_limit=1); assert r.status_code == 400, r.status_code
            msg.append("limit below spent -> 400")
            return "; ".join(msg)
        check("Spend guard (DESKTOP_PLAN)", t_spend)
        # ---- step 6: error handling
        def t_fail():
            s3 = T["s3"]; flag = RUN / "fail.flag"
            jid = upload(s3, pdf12)["id"]; flag.write_text("1")
            assert start(s3, jid).status_code == 200
            j = wait(s3, jid, ("failed", "done", "paused")); assert j["state"] == "failed", j
            err = j.get("error", ""); assert err, j
            flag.unlink()
            assert start(s3, jid).status_code == 200
            j2 = wait(s3, jid, ("done", "failed")); assert j2["state"] == "done", j2
            return f"outage -> failed with message {err[:140]!r}; after outage ends Continue -> done"
        check("E2 provider failure then Continue (C23)", t_fail)
        # ---- step 3 leftovers: key never leaks over API
        def t_leak():
            s3 = T["s3"]; key(s3, "sk-test-LEAKCHECK-9999")
            blob = json.dumps(s3.c.get("/api/config").json()) + json.dumps(s3.c.get("/api/jobs").json())
            assert "LEAKCHECK" not in blob, "key echoed by API"
            hits = [str(p) for p in s3.data.rglob("*") if p.is_file() and b"LEAKCHECK" in p.read_bytes()]
            assert not hits, hits
            noauth = httpx.get(str(s3.c.base_url).rstrip("/") + "/api/config", trust_env=False).status_code
            assert noauth == 401, noauth
            return "key not in /api/config, /api/jobs, or any file under the data folder (incl. job.json, sidecar logs); no-token request -> 401"
        check("B13 key not in API/files", t_leak)
    finally:
        for p in PROCS:
            if p.poll() is None: p.kill()
        (RUN / "results.json").write_text(json.dumps(RESULTS, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n".join(f"{s:5} {i}: {n}" for i, s, n in RESULTS))

main()
