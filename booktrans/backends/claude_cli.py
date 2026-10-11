"""Backend that shells out to the local `claude` CLI (Claude Pro/Max login)."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from .base import LLMBackend


class ClaudeCLIBackend(LLMBackend):
    supports_vision = True

    def _run(self, cmd, **kw):
        """Run `claude -p` with JSON output; record usage and return the text result."""
        if self.model:
            cmd += ["--model", self.model]
        r = subprocess.run(cmd + ["--output-format", "json"],
                           capture_output=True, text=True, **kw)
        try:
            data = json.loads(r.stdout)
        except ValueError:
            data = None
        if r.returncode != 0 or not data or data.get("is_error"):
            sys.exit(f"claude CLI failed: {r.stderr.strip() or r.stdout.strip()}")
        self.usage.record(data.get("usage") or {}, data.get("total_cost_usd"))
        return data.get("result", "").strip()

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
