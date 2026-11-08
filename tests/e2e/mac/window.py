import os, subprocess, sys, time, signal, json
from pathlib import Path
REPO, S = Path(sys.argv[1]), Path(sys.argv[2]); RUN = S/"run"
env = {**os.environ, "PYTHONPATH": f"{REPO}:{Path(__file__).resolve().parent}", "BOOKTRANS_DATA": str(RUN/"windata"), "BOOKTRANS_FAKE_BACKEND": "1",
       "FAKEKR_FILE": str(RUN/"winkr.json"), "PYTHON_KEYRING_BACKEND": "fakekr.FileKR", "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}
out = {}
def children(pid):
    r = subprocess.run(["pgrep", "-P", str(pid)], capture_output=True, text=True).stdout.split()
    return [int(x) for x in r]
def alive(pid):
    try: os.kill(pid, 0); return True
    except OSError: return False
def windows(pid):
    r = subprocess.run(["osascript", "-e", f'tell application "System Events" to get name of every window of (first process whose unix id is {pid})'], capture_output=True, text=True, timeout=20)
    return (r.stdout.strip(), r.stderr.strip()[:200])
def launch():
    t0 = time.time()
    p = subprocess.Popen([str(REPO/".venv/bin/python"), "-m", "booktrans.desktop.shell"], cwd=str(REPO), env=env, stdout=subprocess.DEVNULL, stderr=open(RUN/"shell.err","w"))
    return p, t0
# --- A3/S1 + S2 close
p, t0 = launch(); win = None
while time.time() - t0 < 30:
    kids = children(p.pid)
    w = windows(p.pid)
    if "Book Translator" in w[0]: win = time.time() - t0; break
    time.sleep(0.5)
out["window_title_seen_after_s"] = win; out["window_probe"] = w; out["sidecar_children"] = kids
subprocess.run(["screencapture", "-x", str(RUN/"window.png")])
if win:
    # close via the red button
    r = subprocess.run(["osascript", "-e", f'tell application "System Events" to click button 1 of window 1 of (first process whose unix id is {p.pid})'], capture_output=True, text=True)
    out["close_click"] = r.stderr.strip()[:200] or "clicked"
    for _ in range(100):
        if p.poll() is not None: break
        time.sleep(0.1)
    out["shell_exited_after_close"] = p.poll() is not None
else:
    p.terminate(); p.wait(10)
time.sleep(2)
out["sidecar_alive_after_close"] = [k for k in kids if alive(k)]
for k in out["sidecar_alive_after_close"]: os.kill(k, 9)
# --- A5 kill main
p, t0 = launch()
for _ in range(100):
    kids = children(p.pid)
    if kids: break
    time.sleep(0.3)
time.sleep(3)
p.kill(); p.wait(); time.sleep(3)
out["kill9_sidecar_alive"] = [k for k in kids if alive(k)]
for k in kids:
    if alive(k): os.kill(k, 9)
print(json.dumps(out, indent=1, ensure_ascii=False))
