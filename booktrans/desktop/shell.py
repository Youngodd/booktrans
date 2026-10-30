"""Desktop shell (pywebview prototype): start the sidecar, keep the API key in the OS
credential store, hand the key to the sidecar once per session, show the window.

python -m booktrans.desktop.shell                 open the app window
python -m booktrans.desktop.shell --headless-check  everything except the window (CI)

BOOKTRANS_SIDECAR can name the app program to run with --sidecar (default: this Python running
`-m booktrans.desktop`; a frozen app runs itself). The sidecar must not outlive the shell: on Windows it is put in a
job object that kills it when the shell exits, however the shell ends.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx

SERVICE = "BookTranslator"
ACCOUNT = "api-key"  # the stored secret is "<provider>:<key>"


KEY_PAGES = {  # pages that explain how to get a key; the only URLs the page may open
    "https://console.anthropic.com/settings/keys",
    "https://bailian.console.aliyun.com/?apiKey=1",
    "https://modelstudio.console.alibabacloud.com/?tab=playground#/api-key",
    "https://platform.deepseek.com/api_keys",
}


def sidecar_command():
    """The installed app runs itself with --sidecar; BOOKTRANS_SIDECAR names another such program."""
    exe = os.environ.get("BOOKTRANS_SIDECAR") or (sys.executable if getattr(sys, "frozen", False) else None)
    return [exe, "--sidecar"] if exe else [sys.executable, "-m", "booktrans.desktop"]


def _kill_with_parent_on_windows(proc):
    """Windows: make the OS kill `proc` when this process ends (even if it is killed)."""
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    job = k32.CreateJobObjectW(None, None)

    class BASIC(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class IO(ctypes.Structure):
        _fields_ = [(n, ctypes.c_uint64) for n in ("a", "b", "c", "d", "e", "f")]

    class EXTENDED(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    info = EXTENDED()
    info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    ok = k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
    ok = ok and k32.AssignProcessToJobObject(job, wintypes.HANDLE(int(proc._handle)))
    if not ok:
        raise OSError(ctypes.get_last_error(), "could not put the sidecar in a job object")
    return job  # keep a reference: closing the handle (process exit) kills the sidecar


class Sidecar:
    def __init__(self):
        self.proc = self.base = self.token = self._job = None

    def start(self, timeout=90):
        import tempfile
        from .__main__ import data_dir
        ready = Path(tempfile.mkdtemp(prefix="booktrans-")) / "ready"
        logs = data_dir()
        logs.mkdir(parents=True, exist_ok=True)
        self.log_path = logs / "sidecar.log"
        flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW: no console flash
        with open(self.log_path, "a", encoding="utf-8") as log:
            self.proc = subprocess.Popen(sidecar_command() + ["--ready-file", str(ready)],
                                         stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
        if os.name == "nt":
            self._job = _kill_with_parent_on_windows(self.proc)
        end = time.time() + timeout
        while time.time() < end:
            if ready.exists():
                break
            if self.proc.poll() is not None:
                raise RuntimeError("sidecar exited early:\n" + self.log_path.read_text(
                    encoding="utf-8", errors="replace")[-2000:])
            time.sleep(0.1)
        else:
            raise RuntimeError("sidecar did not start")
        m = re.search(r"port=(\d+) token=(\S+)", ready.read_text(encoding="utf-8"))
        self.base, self.token = f"http://127.0.0.1:{m[1]}", m[2]
        self.http = httpx.Client(base_url=self.base, headers={"X-Booktrans-Token": self.token},
                                 timeout=60)
        while time.time() < end:  # the ready line comes just before the server listens
            try:
                self.http.get("/healthz")
                return self
            except httpx.TransportError:
                time.sleep(0.1)
        raise RuntimeError("sidecar did not answer")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()


def stored_key():
    """(provider, key) from the credential store, or None."""
    import keyring
    value = keyring.get_password(SERVICE, ACCOUNT)
    provider, _, key = (value or "").partition(":")
    return (provider, key) if key else None


PREFS_FILE = "prefs.json"
_prefs_lock = threading.Lock()  # the page calls set_models from several threads
MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}$")


def _prefs_path():
    from .__main__ import data_dir
    return data_dir() / PREFS_FILE


def load_prefs():
    """{provider: {"model": ..., "ocr_model": ...}} the user chose; {} when none or unreadable."""
    try:
        raw = json.loads(_prefs_path().read_text(encoding="utf-8"))["models"]
    except (OSError, ValueError, KeyError, TypeError):
        return {}
    return {p: {k: v for k, v in c.items() if k in ("model", "ocr_model") and isinstance(v, str)
                and (v == "" or MODEL_ID.match(v))}
            for p, c in raw.items() if isinstance(p, str) and isinstance(c, dict)}


class Api:
    """Methods the page can call as window.pywebview.api.<name>(...). The key never goes
    back to the page: it only moves between the credential store and the sidecar."""

    def __init__(self, sidecar):  # underscore names are not exposed to the page
        self._sidecar = sidecar
        self._window = None

    def connection(self):
        return {"base": self._sidecar.base, "token": self._sidecar.token}

    def has_key(self):
        found = stored_key()
        return {"has_key": bool(found), "provider": found[0] if found else "",
                "hint": "…" + found[1][-4:] if found else ""}  # last 4 characters only, never the key

    def use_stored_key(self):
        """Give the stored key to the sidecar for this session; call once at start-up."""
        found = stored_key()
        if not found:
            return {"ok": False, "error": "no stored key"}
        return self._push(*found)

    def save_key(self, provider, key):
        """Check the key with the provider (via the sidecar); store it only if it passes."""
        if not (key or "").strip():
            return {"ok": False, "status": 400, "error": "请输入 key。 Enter a key."}
        result = self._push(provider, key)
        if result["ok"]:
            import keyring
            try:
                keyring.set_password(SERVICE, ACCOUNT, f"{provider}:{key}")
            except Exception as e:  # the key works for this session but could not be kept
                return {"ok": False, "status": 500,
                        "error": f"key 可用但无法保存到系统凭据库 The key works but could not be stored: {type(e).__name__}"}
        return result

    def delete_key(self):
        import keyring
        try:
            keyring.delete_password(SERVICE, ACCOUNT)
        except keyring.errors.PasswordDeleteError:
            pass
        self._sidecar.http.delete("/api/key")  # the running session forgets it too
        return {"ok": True}

    def _push(self, provider, key):
        r = self._sidecar.http.put("/api/key", json={"api_key": key, "provider": provider})
        return {"ok": r.status_code == 200, "status": r.status_code,
                "error": "" if r.status_code == 200 else r.json().get("detail", "")}

    def get_models(self):
        """The model choices kept per provider (not secret; stored beside the app's data)."""
        return load_prefs()

    def set_models(self, provider, model, ocr_model):
        """Remember the model and OCR model chosen for one provider. Empty means the default."""
        model, ocr_model = (model or "").strip(), (ocr_model or "").strip()
        if not isinstance(provider, str) or any(v and not MODEL_ID.match(v) for v in (model, ocr_model)):
            return {"ok": False}
        with _prefs_lock:
            prefs = load_prefs()
            prefs[provider] = {"model": model, "ocr_model": ocr_model}
            path = _prefs_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"models": prefs}), encoding="utf-8")
            os.replace(tmp, path)
        return {"ok": True}

    def save_pdf(self, job_id, suggested_name):
        """Ask where to save the finished PDF, then copy it there."""
        import webview
        dest = self._window.create_file_dialog(webview.SAVE_DIALOG, save_filename=suggested_name,
                                              file_types=("PDF (*.pdf)",))
        if not dest:
            return {"ok": False}
        dest = dest if isinstance(dest, str) else dest[0]
        r = self._sidecar.http.get(f"/api/jobs/{job_id}/download")
        with open(dest, "wb") as f:
            f.write(r.content)
        return {"ok": r.status_code == 200, "path": dest}


    def reveal(self, path):
        """Show a saved file in the system file manager."""
        if os.name == "nt":
            subprocess.run(["explorer", "/select,", os.path.normpath(path)])
        elif sys.platform == "darwin":
            subprocess.run(["open", "-R", path])
        else:
            subprocess.run(["xdg-open", os.path.dirname(path)])
        return {"ok": True}

    def open_url(self, url):
        """Open one of the provider pages the app links to in the user's browser."""
        import webbrowser
        if url not in KEY_PAGES:
            return {"ok": False}
        webbrowser.open(url)
        return {"ok": True}


def headless_check():
    """Start the sidecar and exercise the key flow without opening a window."""
    side = Sidecar().start()
    api = Api(side)
    print("sidecar pid", side.proc.pid)
    assert api.save_key("api", "sk-ant-shell-check-key-000000")["ok"], "key was not accepted"
    found = api.has_key()
    assert found["has_key"] and found["provider"] == "api" and found["hint"] == "…0000", found
    side.http.delete("/api/key")  # a fresh session: the sidecar has forgotten the key...
    assert not side.http.get("/api/config").json()["has_key"]
    assert api.use_stored_key()["ok"]  # ...and the shell hands it over again
    assert side.http.get("/api/config").json()["has_key"]
    api.delete_key()
    assert api.has_key()["has_key"] is False
    print("SHELL OK: key stored, handed to the sidecar, deleted")
    if "--hold" in sys.argv:  # CI: stay alive so the test can kill this process
        print("HOLDING", flush=True)
        time.sleep(600)
    side.stop()


def main():
    if "--headless-check" in sys.argv:
        return headless_check()
    import webview
    side = Sidecar().start()
    api = Api(side)
    api.use_stored_key()
    # TODO(M2): the page must send the token header; the prototype only opens it.
    api._window = webview.create_window("Book Translator", f"{side.base}/#token={side.token}",
                                       js_api=api, width=1000, height=760)
    try:
        webview.start()
    finally:
        side.stop()


if __name__ == "__main__":
    main()
