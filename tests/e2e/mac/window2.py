import os, subprocess, sys, time, json
from pathlib import Path
REPO, S = Path(sys.argv[1]), Path(sys.argv[2]); RUN = S/"run"
env = {**os.environ, "PYTHONPATH": f"{REPO}:{Path(__file__).resolve().parent}", "BOOKTRANS_DATA": str(RUN/"windata2"), "BOOKTRANS_FAKE_BACKEND": "1",
       "FAKEKR_FILE": str(RUN/"winkr2.json"), "PYTHON_KEYRING_BACKEND": "fakekr.FileKR", "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}
def osa(s): return subprocess.run(["osascript", "-e", s], capture_output=True, text=True, timeout=20)
t0 = time.time()
p = subprocess.Popen([str(REPO/".venv/bin/python"), "-m", "booktrans.desktop.shell"], cwd=str(REPO), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
q = f'(first process whose unix id is {p.pid})'
seen = None
while time.time() - t0 < 40:
    if "Book Translator" in osa(f'tell application "System Events" to get name of every window of {q}').stdout: seen = time.time() - t0; break
    time.sleep(0.2)
print("window seen after", seen)
time.sleep(4)  # let the page render
osa(f'tell application "System Events" to set frontmost of {q} to true'); time.sleep(1)
pos = osa(f'tell application "System Events" to get position of window 1 of {q}').stdout.strip().split(", ")
size = osa(f'tell application "System Events" to get size of window 1 of {q}').stdout.strip().split(", ")
print("pos", pos, "size", size)
subprocess.run(["screencapture", "-x", "-R", f"{pos[0]},{pos[1]},{size[0]},{size[1]}", str(RUN/"app-window.png")])
osa(f'tell application "System Events" to click button 1 of window 1 of {q}')
for _ in range(100):
    if p.poll() is not None: break
    time.sleep(0.1)
print("exited", p.poll() is not None)
if p.poll() is None: p.kill()
