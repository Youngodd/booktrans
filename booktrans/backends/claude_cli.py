"""Backend that shells out to the local `claude` CLI (Claude Pro/Max login)."""
import json
import subprocess
import tempfile
from pathlib import Path

from .base import BackendError, LLMBackend


TIMEOUT = 900  # seconds for one call; a hung process must not hang the whole job


class ClaudeCLIBackend(LLMBackend):
    supports_vision = True

    def _run(self, cmd, **kw):
        """Run `claude -p` with JSON output; record usage and return the text result."""
        if self.model:
            cmd += ["--model", self.model]
        try:  # UTF-8 whatever the system locale is (a Chinese Windows would read cp936)
            r = subprocess.run(cmd + ["--output-format", "json"], capture_output=True,
                               encoding="utf-8", errors="replace", timeout=TIMEOUT, **kw)
        except FileNotFoundError:
            raise ValueError("The claude command was not found. Install Claude Code and sign in, "
                             "or choose another backend (for example --backend api).") from None
        except subprocess.TimeoutExpired:
            raise BackendError(f"claude CLI did not answer within {TIMEOUT} seconds") from None
        try:
            data = json.loads(r.stdout)
        except ValueError:
            data = None
        if r.returncode != 0 or not data or data.get("is_error"):
            msg = (data or {}).get("result") or r.stderr.strip() or r.stdout.strip()
            raise BackendError(f"claude CLI failed: {msg}")
        self.usage.record(data.get("usage") or {}, data.get("total_cost_usd"))
        return (data.get("result") or "").strip()

    def complete(self, system, user, max_tokens=4096):
        cmd = ["claude", "-p", "--tools", "", "--no-session-persistence",
               "--system-prompt", system]
        return self._run(cmd, input=user)

    def ocr_image(self, jpeg, prompt):
        # let the CLI's Read tool open the page image
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "page.jpg").write_bytes(jpeg)
            cmd = ["claude", "-p", "Read the image file page.jpg. " + prompt,
                   "--tools", "Read", "--allowedTools", "Read",
                   "--no-session-persistence"]
            return self._run(cmd, cwd=tmp, stdin=subprocess.DEVNULL)
