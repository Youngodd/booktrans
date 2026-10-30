"""Run the desktop sidecar: python -m booktrans.desktop

Tells the shell that spawned it where to connect, as one line `port=<port> token=<token>`
written to the file given with `--ready-file` (a windowed Windows program has no stdout), and
also printed as `BOOKTRANS_READY ...` when there is one. Binds to 127.0.0.1 on a random port.
"""
import os
import re
import secrets
import socket
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import uvicorn

from ..backends.base import LLMBackend
from ..web.app import create_app


def data_dir():
    """BOOKTRANS_DATA, else %APPDATA%\\BookTranslator on Windows, else ~/.booktranslator."""
    if os.environ.get("BOOKTRANS_DATA"):
        return Path(os.environ["BOOKTRANS_DATA"])
    if os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "BookTranslator"
    return Path.home() / ".booktranslator"


class FakeBackend(LLMBackend):
    """Offline stand-in for CI smoke tests (BOOKTRANS_FAKE_BACKEND=1): `[n] 译n` per block."""

    provider = "fake"  # priced at ¥1 per call (see main), so the spend guard can be tried offline

    def complete(self, system, user, max_tokens=4096):
        self.usage.record({"input_tokens": 1000, "output_tokens": 1000})
        nums = re.findall(r"(?m)^\[(\d+)\]", user)
        return "\n".join(f"[{n}] 译{n}" for n in nums) if nums else "译:" + user


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    ready_file = argv[argv.index("--ready-file") + 1] if "--ready-file" in argv else None
    token = secrets.token_urlsafe(24)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    if os.environ.get("BOOKTRANS_FAKE_BACKEND") == "1":
        from .. import spend
        spend.PRICES["fake"] = {"text": (500.0, 500.0), "vision": (500.0, 500.0)}  # ¥1 per fake call
    extra = {"backend_factory": lambda key, provider="api", **chosen: FakeBackend()} \
        if os.environ.get("BOOKTRANS_FAKE_BACKEND") == "1" else {}
    app = create_app(data_dir(), desktop=True, token=token, **extra,
                     executor=ThreadPoolExecutor(1))  # threads: no frozen-multiprocessing
    line = f"port={port} token={token}"
    if ready_file:  # written whole, then renamed, so the reader never sees half a line
        Path(ready_file + ".tmp").write_text(line, encoding="utf-8")
        os.replace(ready_file + ".tmp", ready_file)
    if sys.stdout:
        print("BOOKTRANS_READY " + line, flush=True)
    uvicorn.Server(uvicorn.Config(app, log_level="warning")).run(sockets=[sock])


if __name__ == "__main__":
    sys.exit(main())
