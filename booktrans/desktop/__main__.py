"""Run the desktop sidecar: python -m booktrans.desktop

Prints one line, `BOOKTRANS_READY port=<port> token=<token>`, once the server is up, so the
shell that spawned it knows where to connect. Binds to 127.0.0.1 on a random port.
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

    def complete(self, system, user, max_tokens=4096):
        nums = re.findall(r"(?m)^\[(\d+)\]", user)
        return "\n".join(f"[{n}] 译{n}" for n in nums) if nums else "译:" + user


def main():
    token = secrets.token_urlsafe(24)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    extra = {"backend_factory": lambda key, provider="api": FakeBackend()} \
        if os.environ.get("BOOKTRANS_FAKE_BACKEND") == "1" else {}
    app = create_app(data_dir(), desktop=True, token=token, **extra,
                     executor=ThreadPoolExecutor(1))  # threads: no frozen-multiprocessing
    print(f"BOOKTRANS_READY port={port} token={token}", flush=True)
    uvicorn.Server(uvicorn.Config(app, log_level="warning")).run(sockets=[sock])


if __name__ == "__main__":
    sys.exit(main())
