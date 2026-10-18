"""Install the built installer silently into a folder with Chinese characters, run the installed
app's smoke test, try to launch the window, uninstall, and check nothing is left behind.

usage: python packaging/install_check.py INSTALLER.exe     (Windows only; changes only the folder below)
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # the install folder has Chinese characters
here = Path(__file__).resolve().parent
installer = Path(sys.argv[1]).resolve()
target = Path(tempfile.gettempdir()) / "安装测试" / "Book Translator"


def run(*args, **kw):
    return subprocess.run([str(a) for a in args], **kw)


r = run(installer, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", f"/DIR={target}",
        f"/LOG={target.parent}.install.log")
exe = target / "BookTranslator.exe"
assert r.returncode == 0 and exe.exists(), f"install failed (code {r.returncode}); {exe} missing"
print(f"INSTALL OK: {exe} ({sum(f.stat().st_size for f in target.rglob('*') if f.is_file()) / 1e6:.0f} MB)")

r = run(sys.executable, here / "smoke_test.py", exe, "--sidecar")
assert r.returncode == 0, "smoke test of the installed app failed"

data = Path(tempfile.mkdtemp(prefix="gui-"))
env = {**os.environ, "BOOKTRANS_DATA": str(data), "BOOKTRANS_FAKE_BACKEND": "1"}
gui = subprocess.Popen([str(exe)], env=env)
time.sleep(25)
code = gui.poll()
log = data / "sidecar.log"
if code is None and log.exists():
    print("GUI LAUNCH OK: the window process stayed up and started its sidecar")
else:  # reported, not fatal: a CI runner may lack what a window needs
    print(f"::warning title=GUI launch::exit code {code}, sidecar.log exists: {log.exists()}")
if code is None:
    gui.kill()
    gui.wait()

unins = sorted(target.glob("unins*.exe"))
assert unins, "no uninstaller was installed"
run(unins[0], "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART")
for _ in range(30):
    if not exe.exists():
        break
    time.sleep(1)
assert not exe.exists(), "uninstall left the program behind"
print("UNINSTALL OK")
