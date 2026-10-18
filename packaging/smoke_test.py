"""Smoke-test the desktop sidecar: start it, translate a 2-page PDF with the fake backend,
check the output has Chinese text, and report the bundle size.

usage: python packaging/smoke_test.py [--bundle DIR] COMMAND [ARGS...]
e.g.   python packaging/smoke_test.py dist/booktrans-sidecar/booktrans-sidecar.exe
       python packaging/smoke_test.py python -m booktrans.desktop
The data folder and the book's file name contain Chinese characters on purpose.
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import fitz
import httpx


def make_book(path):
    doc = fitz.open()
    for n in range(2):
        pg = doc.new_page()
        pg.insert_text((72, 100), f"Chapter heading {n}", fontsize=20)
        pg.insert_textbox(fitz.Rect(72, 130, 500, 300), "This is a body paragraph of the book "
                          "that is long enough to wrap across several lines on the page.",
                          fontsize=11)
    doc.save(path)


def dir_mb(path):
    return sum(f.stat().st_size for f in Path(path).rglob("*") if f.is_file()) / 1e6


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", help="folder to measure and report the size of")
    ap.add_argument("command", nargs=argparse.REMAINDER)
    args = ap.parse_args()
    work = Path(tempfile.mkdtemp(prefix="书-")) # non-ASCII path
    env = {**os.environ, "BOOKTRANS_DATA": str(work / "数据"), "BOOKTRANS_FAKE_BACKEND": "1",
           "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.Popen(args.command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            env=env, text=True, encoding="utf-8")
    log = []
    threading.Thread(target=lambda: [log.append(l) for l in proc.stdout], daemon=True).start()
    try:
        end = time.time() + 90
        while time.time() < end and not any("BOOKTRANS_READY" in l for l in log):
            if proc.poll() is not None:
                sys.exit("sidecar exited early:\n" + "".join(log))
            time.sleep(0.2)
        m = re.search(r"port=(\d+) token=(\S+)", "".join(log))
        assert m, "no ready line:\n" + "".join(log)
        c = httpx.Client(base_url=f"http://127.0.0.1:{m[1]}", headers={"X-Booktrans-Token": m[2]},
                         timeout=30)
        for _ in range(50):  # the ready line comes just before the server listens
            try:
                c.get("/healthz")
                break
            except httpx.TransportError:
                time.sleep(0.2)
        assert httpx.get(c.base_url.join("/api/config"), timeout=10).status_code == 401
        book = work / "化学之树.pdf"
        make_book(book)
        job = c.post("/api/jobs", files={"file": (book.name, book.read_bytes())}).json()
        assert job["filename"] == "化学之树.pdf", job
        r = c.put("/api/key", json={"api_key": "sk-ant-smoke-test-key-0000000", "provider": "api"})
        assert r.status_code == 200, r.text
        assert c.post(f"/api/jobs/{job['id']}/start", json={"auto_glossary": False}).status_code == 200
        end = time.time() + 120
        while time.time() < end:
            j = c.get(f"/api/jobs/{job['id']}").json()
            if j["state"] in ("done", "failed"):
                break
            time.sleep(0.3)
        assert j["state"] == "done", j
        pdf = c.get(f"/api/jobs/{job['id']}/download").content
        out = fitz.open(stream=pdf, filetype="pdf")
        text = "".join(p.get_text() for p in out)
        assert out.page_count >= 2 and "译" in text, f"pages={out.page_count} text={text[:200]!r}"
        print("SMOKE OK: translated 2 pages, Chinese text present in the output PDF")
        if args.bundle:
            print(f"BUNDLE SIZE: {dir_mb(args.bundle):.0f} MB")
    finally:
        proc.kill()
        proc.wait()


if __name__ == "__main__":
    main()
