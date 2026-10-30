"""Drive the real desktop window (pywebview) through first run, key save, upload, translate.

usage: python packaging/ui_check.py       (opens a window for a few seconds)
Uses the fake backend and an in-memory keyring, so no provider is called and the system
credential store is untouched. Exits non-zero if any step fails.
"""
import json
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
        # a Chinese-language system starts on Qwen; this check uses Anthropic
        assert window.evaluate_js("navigator.language.startsWith('zh') ? document.getElementById('provider').value === 'qwen' : true"), "locale default"
        window.evaluate_js("document.getElementById('provider').value = 'api'")
        window.evaluate_js("document.getElementById('key').value='sk-ant-ui-check-key-00000000'; document.getElementById('btn-savekey').click()")
        until(window, "document.getElementById('keymsg').classList.contains('done')")  # saved; the panel stays in view
        assert shell.stored_key() == ("api", "sk-ant-ui-check-key-00000000")
        assert side.http.get("/api/config").json()["has_key"]
        # settings can be reopened after the key was saved
        window.evaluate_js("document.getElementById('btn-settings').click()")
        window.evaluate_js("document.getElementById('btn-usingkey').click()")  # the button next to "Provider:"
        # a book (uploaded over HTTP; the file chooser is native) then reload: the page reopens it
        book = work / "化学之树.pdf"
        make_book(book)
        side.http.post("/api/jobs", files={"file": (book.name, book.read_bytes())})
        window.load_url(f"{side.base}/en?reload=1#token={side.token}")
        until(window, "document.getElementById('bookinfo').textContent.includes('化学之树.pdf')")
        # the pickers: switch to Qwen (which reads scanned pages), choose a listed model and a typed OCR model
        window.evaluate_js("document.getElementById('btn-usingkey').click(); document.getElementById('keymsg').className = 'msg'; "
                           "document.getElementById('provider').value = 'qwen'; "
                           "document.getElementById('key').value='sk-qwen-ui-check-key-00000000'; document.getElementById('btn-savekey').click()")
        until(window, "document.getElementById('keymsg').classList.contains('done')")
        assert window.evaluate_js("document.getElementById('model').value") == "qwen-plus", "provider default first"
        assert window.evaluate_js("document.getElementById('ocr-model').disabled"), "OCR model is off until OCR is ticked"
        window.evaluate_js("""
          const pick = (id, v) => { const e = document.getElementById(id); e.value = v; e.dispatchEvent(new Event('change')); };
          pick('model', 'qwen-max');
          document.getElementById('ocr').click();
          pick('ocr-model', '__custom__');
          const c = document.getElementById('ocr-model-custom'); c.value = 'qwen-vl-ui-check'; c.dispatchEvent(new Event('input'));
        """)
        assert "Rate shown" in window.evaluate_js("document.getElementById('estimate').textContent"), "estimate marked approximate"
        want, prefs = {"model": "qwen-max", "ocr_model": "qwen-vl-ui-check"}, None
        for _ in range(50):  # the page saves in the background; wait for the file
            try:
                prefs = json.loads((work / "data" / "prefs.json").read_text(encoding="utf-8"))["models"]
            except (OSError, ValueError):
                prefs = None
            if prefs and prefs.get("qwen") == want:
                break
            time.sleep(0.2)
        assert prefs and prefs["qwen"] == want, prefs
        window.load_url(f"{side.base}/en?reload=2#token={side.token}")  # restored on launch
        until(window, "document.getElementById('bookinfo').textContent.includes('化学之树.pdf')")
        until(window, "document.getElementById('model').value === 'qwen-max' && document.getElementById('ocr-model-custom').value === 'qwen-vl-ui-check'")
        window.evaluate_js("document.getElementById('ocr').click()")
        # the review step: tick it, translate, accept the names
        window.evaluate_js("document.getElementById('limit').value = '1.5'")  # the fake backend costs ¥1 a call
        window.evaluate_js("rights.checked = true; review.checked = true; btn_start = document.getElementById('btn-start'); btn_start.click()")
        until(window, "!document.getElementById('step-names').classList.contains('hidden') && "
                      "!document.getElementById('btn-names-skip').classList.contains('hidden')", 60)
        window.evaluate_js("document.getElementById('btn-names-skip').click()")
        # the limit stops the book after one page and asks
        until(window, "!document.getElementById('decision').classList.contains('hidden')", 90)
        text = window.evaluate_js("document.getElementById('decision-text').textContent")
        assert "¥1.00" in text and "1.50" in text and "1/2" in text, text
        window.evaluate_js("document.getElementById('btn-finish-partial').click()")
        until(window, "!document.getElementById('btn-save').classList.contains('hidden')", 90)
        assert "translated pages only" in window.evaluate_js("document.getElementById('stage').textContent")
        # both choices were sent with the start request (the job keeps them; the key is never stored there)
        saved = [json.loads(p.read_text(encoding="utf-8")) for p in (work / "data" / "jobs").glob("*/job.json")]
        assert any(j.get("model") == "qwen-max" and j.get("ocr_model") == "qwen-vl-ui-check" for j in saved), saved
        # the key never reached the page
        assert "ui-check-key" not in window.evaluate_js("document.documentElement.outerHTML")
        result["ok"] = True
        print("UI CHECK OK: first run, key saved, book reopened, model and OCR model chosen and restored, glossary step, spend limit stop, finished with the translated pages")
    except Exception as e:
        print("UI CHECK FAILED:", repr(e))
        print("page text:", window.evaluate_js("document.body.innerText")[:600])
    finally:
        window.destroy()


def main():
    side = shell.Sidecar().start()
    api = shell.Api(side)
    window = webview.create_window("ui check", f"{side.base}/en#token={side.token}", js_api=api)  # the checks read English text
    api._window = window
    threading.Thread(target=run, args=(window, side), daemon=True).start()
    try:
        webview.start()
    finally:
        side.stop()
    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
