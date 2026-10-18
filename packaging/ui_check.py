"""Drive the real desktop window (pywebview) through first run, key save, upload, translate.

usage: python packaging/ui_check.py       (opens a window for a few seconds)
Uses the fake backend and an in-memory keyring, so no provider is called and the system
credential store is untouched. Exits non-zero if any step fails.
"""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

import keyring
from keyring.backend import KeyringBackend

sys.path.insert(0, str(Path(__file__).resolve().parent))
from smoke_test import make_book  # noqa: E402


class Mem(KeyringBackend):
    priority = 1
    d = {}

    def get_password(self, s, u):
        return self.d.get((s, u))

    def set_password(self, s, u, p):
        self.d[(s, u)] = p

    def delete_password(self, s, u):
        self.d.pop((s, u), None)


keyring.set_keyring(Mem())
work = Path(tempfile.mkdtemp())
os.environ.update(BOOKTRANS_FAKE_BACKEND="1", BOOKTRANS_DATA=str(work / "data"))

import webview  # noqa: E402
from booktrans.desktop import shell  # noqa: E402

result = {"ok": False}


def until(window, js, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        v = window.evaluate_js(js)
        if v:
            return v
        time.sleep(0.3)
    raise AssertionError("timed out waiting for: " + js)


def run(window, side):
    try:
        until(window, "window.pywebview && window.pywebview.api && document.readyState === 'complete'")
        time.sleep(1)
        # first run: no key stored, so the key panel is open
        assert until(window, "!document.getElementById('step-key').classList.contains('hidden')"), "no first-run panel"
        # a Chinese-language system starts on Qwen; this check uses Anthropic
        assert window.evaluate_js("navigator.language.startsWith('zh') ? document.getElementById('provider').value === 'qwen' : true"), "locale default"
        window.evaluate_js("document.getElementById('provider').value = 'api'")
        window.evaluate_js("document.getElementById('proxy').value='http://127.0.0.1:7890'; document.getElementById('btn-saveproxy').click()")
        until(window, "document.getElementById('proxymsg').textContent.includes('127.0.0.1:7890')")
        assert side.http.get("/api/config").json()["proxy"] == "127.0.0.1:7890"
        window.evaluate_js("document.getElementById('proxy').value=''; document.getElementById('btn-saveproxy').click()")
        until(window, "document.getElementById('proxymsg').textContent.includes('Cleared')")
        window.evaluate_js("document.getElementById('key').value='sk-ant-ui-check-key-00000000'; document.getElementById('btn-savekey').click()")
        until(window, "document.getElementById('step-key').classList.contains('hidden')")
        assert shell.stored_key() == ("api", "sk-ant-ui-check-key-00000000")
        assert side.http.get("/api/config").json()["has_key"]
        # a book (uploaded over HTTP; the file chooser is native) then reload: the page reopens it
        book = work / "化学之树.pdf"
        make_book(book)
        side.http.post("/api/jobs", files={"file": (book.name, book.read_bytes())})
        window.load_url(f"{side.base}/?reload=1#token={side.token}")
        until(window, "document.getElementById('bookinfo').textContent.includes('化学之树.pdf')")
        # the review step: tick it, translate, accept the names
        window.evaluate_js("rights.checked = true; review.checked = true; btn_start = document.getElementById('btn-start'); btn_start.click()")
        until(window, "!document.getElementById('step-names').classList.contains('hidden') && "
                      "!document.getElementById('btn-names-skip').classList.contains('hidden')", 60)
        window.evaluate_js("document.getElementById('btn-names-skip').click()")
        until(window, "!document.getElementById('btn-save').classList.contains('hidden')", 90)
        assert "Done" in window.evaluate_js("document.getElementById('stage').textContent")
        # the key never reached the page
        assert "ui-check-key" not in window.evaluate_js("document.documentElement.outerHTML")
        result["ok"] = True
        print("UI CHECK OK: first run, proxy set and cleared, key saved, book reopened, glossary step, translated")
    except Exception as e:
        print("UI CHECK FAILED:", repr(e))
        print("page text:", window.evaluate_js("document.body.innerText")[:600])
    finally:
        window.destroy()


def main():
    side = shell.Sidecar().start()
    api = shell.Api(side)
    window = webview.create_window("ui check", f"{side.base}/#token={side.token}", js_api=api)
    api._window = window
    threading.Thread(target=run, args=(window, side), daemon=True).start()
    try:
        webview.start()
    finally:
        side.stop()
    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
