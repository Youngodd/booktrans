"""Check that killing the shell also ends the sidecar (needs the Windows job object).

usage: python packaging/orphan_test.py SHELL_COMMAND [ARGS...]   (BOOKTRANS_SIDECAR picks the sidecar)
Runs the shell in --headless-check --hold mode, kills it hard, and expects the sidecar to be gone.
"""
import os
import re
import subprocess
import sys
import threading
import time


def alive(pid):
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True,
                             text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def main():
    env = {**os.environ, "BOOKTRANS_FAKE_BACKEND": "1", "PYTHONIOENCODING": "utf-8"}
    shell = subprocess.Popen(sys.argv[1:] + ["--headless-check", "--hold"], env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    log = []
    threading.Thread(target=lambda: [log.append(l) for l in shell.stdout], daemon=True).start()
    end = time.time() + 120
    while time.time() < end and not any("HOLDING" in l for l in log):
        if shell.poll() is not None:
            sys.exit("shell exited early:\n" + "".join(log))
        time.sleep(0.2)
    text = "".join(log)
    assert "HOLDING" in text, "shell never reached the hold point:\n" + text
    sidecar_pid = int(re.search(r"sidecar pid (\d+)", text)[1])
    assert alive(sidecar_pid), "sidecar is not running"
    shell.kill()  # a hard kill: no cleanup code runs in the shell
    shell.wait()
    for _ in range(50):
        if not alive(sidecar_pid):
            print(f"ORPHAN TEST OK: sidecar {sidecar_pid} ended with the shell")
            return
        time.sleep(0.2)
    os.kill(sidecar_pid, 9) if os.name != "nt" else subprocess.run(["taskkill", "/F", "/PID", str(sidecar_pid)])
    sys.exit(f"ORPHAN TEST FAILED: sidecar {sidecar_pid} outlived the shell")


if __name__ == "__main__":
    main()
