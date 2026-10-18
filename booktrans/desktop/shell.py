"""Desktop shell (pywebview prototype): start the sidecar, keep the API key in the OS
credential store, hand the key to the sidecar once per session, show the window.

python -m booktrans.desktop.shell                 open the app window
python -m booktrans.desktop.shell --headless-check  everything except the window (CI)

BOOKTRANS_SIDECAR can name the app program to run with --sidecar (default: this Python running
`-m booktrans.desktop`; a frozen app runs itself). The sidecar must not outlive the shell: on Windows it is put in a
job object that kills it when the shell exits, however the shell ends.
"""
import os
import re
import shutil
import subprocess
import sys
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
        return {"has_key": bool(found), "provider": found[0] if found else ""}

    def use_stored_key(self):
        """Give the stored key to the sidecar for this session; call once at start-up."""
        found = stored_key()
        if not found:
            return {"ok": False, "error": "no stored key"}
        return self._push(*found)

    def save_key(self, provider, key):
        """Check the key with the provider (via the sidecar); store it only if it passes."""
        result = self._push(provider, key)
        if result["ok"]:
            import keyring
            keyring.set_password(SERVICE, ACCOUNT, f"{provider}:{key}")
        return result

    def delete_key(self):
        import keyring
        try:
            keyring.delete_password(SERVICE, ACCOUNT)
        except keyring.errors.PasswordDeleteError:
            pass
        self._sidecar.http.delete("/api/key")
        return {"ok": True}

    def get_proxy(self):
        """The saved proxy as host:port (never with credentials)."""
        return {"proxy": self._sidecar.http.get("/api/config").json().get("proxy", "")}

    def use_stored_proxy(self):
        import keyring
        url = keyring.get_password(SERVICE, "proxy")
        if url:
            self._sidecar.http.put("/api/proxy", json={"url": url})
        return self.get_proxy()

    def set_proxy(self, url):
        """Check the address, give it to the sidecar, and keep it (it may hold a password)."""
        import keyring
        r = self._sidecar.http.put("/api/proxy", json={"url": url})
        if r.status_code != 200:
            return {"ok": False, "error": r.json().get("detail", "")}
        if url.strip():
            keyring.set_password(SERVICE, "proxy", url.strip())
        else:
            try:
                keyring.delete_password(SERVICE, "proxy")
            except keyring.errors.PasswordDeleteError:
                pass
        return {"ok": True, "proxy": r.json()["proxy"]}

    def _push(self, provider, key):
        r = self._sidecar.http.put("/api/key", json={"api_key": key, "provider": provider})
        return {"ok": r.status_code == 200, "status": r.status_code,
                "error": "" if r.status_code == 200 else r.json().get("detail", "")}

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
    assert api.has_key() == {"has_key": True, "provider": "api"}
    side.http.delete("/api/key")  # a fresh session: the sidecar has forgotten the key...
    assert not side.http.get("/api/config").json()["has_key"]
    assert api.use_stored_key()["ok"]  # ...and the shell hands it over again
    assert side.http.get("/api/config").json()["has_key"]
    api.delete_key()
    assert api.has_key()["has_key"] is False
    assert api.set_proxy("http://u:pw@127.0.0.1:7890") == {"ok": True, "proxy": "127.0.0.1:7890"}
    assert not api.set_proxy("nonsense")["ok"]
    side.http.put("/api/proxy", json={"url": ""})  # a fresh session: the sidecar has forgotten it...
    assert api.use_stored_proxy() == {"proxy": "127.0.0.1:7890"}  # ...and the shell restores it
    assert api.set_proxy("") == {"ok": True, "proxy": ""} and api.get_proxy() == {"proxy": ""}
    print("SHELL OK: key and proxy stored, handed to the sidecar, deleted")
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
    api.use_stored_proxy()
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
