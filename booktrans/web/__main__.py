"""Run the web service: python -m booktrans.web  (BOOKTRANS_DATA, PORT, BOOKTRANS_WORKERS)."""
import os

import uvicorn

from .app import create_app

if __name__ == "__main__":
    uvicorn.run(create_app(), host=os.environ.get("HOST", "127.0.0.1"),
                port=int(os.environ.get("PORT", "8000")))
