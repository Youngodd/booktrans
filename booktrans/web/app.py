"""The web service: upload a book, start a translation with your own API key, download."""
import asyncio
import os
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..pipeline import total_pages
from ..readers import parse_range
from . import jobs
from .jobs import JobStore

STATIC = Path(__file__).parent / "static"
EXTENSIONS = (".pdf", ".epub", ".txt")
EST_COST_PER_PAGE = 0.017  # USD on the Anthropic API, measured on a scanned history book
ACTIVE = ("queued", "running")
WEB_PROVIDERS = ("api", "qwen", "qwen-intl", "deepseek")  # bring-your-own-key suppliers


class StartRequest(BaseModel):
    api_key: str
    provider: str = "api"
    pages: str = ""
    preview: bool = False
    ocr: bool = False


def _setting(value, env, default):
    """An explicit argument wins, then the environment variable, then the default."""
    return value if value is not None else int(os.environ.get(env, default))


def create_app(data_dir=None, *, executor=None, backend_factory=jobs.default_backend,
               max_upload_mb=None, max_pages=None, retention_hours=None):
    """Build the app. `executor` runs jobs (default: a pool of worker processes).

    Limits come from the arguments, else BOOKTRANS_MAX_UPLOAD_MB (60),
    BOOKTRANS_MAX_PAGES (400) and BOOKTRANS_RETENTION_HOURS (24).
    """
    max_upload_mb = _setting(max_upload_mb, "BOOKTRANS_MAX_UPLOAD_MB", 60)
    max_pages = _setting(max_pages, "BOOKTRANS_MAX_PAGES", 400)
    retention_hours = _setting(retention_hours, "BOOKTRANS_RETENTION_HOURS", 24)
    data_dir = data_dir or os.environ.get("BOOKTRANS_DATA", "data")
    store = JobStore(Path(data_dir) / "jobs")
    executor = executor or ProcessPoolExecutor(int(os.environ.get("BOOKTRANS_WORKERS", "2")))
    app = FastAPI(title="Book translator", docs_url=None, redoc_url=None)
    app.state.store = store

    @app.on_event("startup")
    async def _cleanup():
        """Delete expired jobs now and then every hour while the server runs."""
        store.cleanup(retention_hours * 3600)

        async def hourly():
            while True:
                await asyncio.sleep(3600)
                await asyncio.to_thread(store.cleanup, retention_hours * 3600)
        app.state.cleanup_task = asyncio.create_task(hourly())

    def get_job(job_id):
        job = store.read(job_id)
        if job is None:
            raise HTTPException(404, "Unknown job (it may have been deleted).")
        return job

    def public(job):
        keys = ("id", "filename", "state", "stage", "done", "total", "error", "pages_total",
                "range", "preview", "usage")
        return {k: job[k] for k in keys if k in job} | {"est_cost_per_page": EST_COST_PER_PAGE}

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})

    @app.post("/api/jobs")
    async def upload(file: UploadFile = File(...)):
        ext = Path(file.filename or "").suffix.lower()
        if ext not in EXTENSIONS:
            raise HTTPException(400, "Upload a .pdf, .epub or .txt file.")
        job_id = store.new(file.filename, ocr=False, range="", pages_total=0)
        path = store.dir(job_id) / ("input" + ext)
        size = 0
        with open(path, "wb") as f:
            while chunk := await file.read(1 << 20):
                size += len(chunk)
                if size > max_upload_mb << 20:
                    store.delete(job_id)
                    raise HTTPException(413, f"The file is larger than {max_upload_mb} MB.")
                f.write(chunk)
        try:
            n = total_pages(path)
        except Exception:
            store.delete(job_id)
            raise HTTPException(400, "This file could not be read as a book.")
        store.write(job_id, pages_total=n)
        return public(store.read(job_id))

    @app.get("/api/jobs/{job_id}")
    def status(job_id: str):
        return public(get_job(job_id))

    @app.post("/api/jobs/{job_id}/start")
    def start(job_id: str, req: StartRequest):
        job = get_job(job_id)
        if job["state"] in ACTIVE:
            raise HTTPException(409, "This job is already running.")
        key = req.api_key.strip()
        if req.provider not in WEB_PROVIDERS:
            raise HTTPException(400, "Unknown provider.")
        if len(key) < 8 or (req.provider == "api" and not key.startswith("sk-")):
            raise HTTPException(400, "Enter your API key for the chosen provider.")
        try:
            idx = parse_range(req.pages.strip() or None, job["pages_total"])
        except ValueError as e:
            raise HTTPException(400, str(e))
        if not idx:
            raise HTTPException(400, "That page range is outside the book.")
        if len(idx) > max_pages:
            raise HTTPException(400, f"At most {max_pages} pages per job; choose a range.")
        rng = f"{idx[0] + 1}-{idx[-1] + 1}"
        if req.preview:
            rng = jobs.preview_range(rng, job["pages_total"])
        store.write(job_id, state="queued", stage="", done=0, total=0, error="", ocr=req.ocr,
                    range=rng, preview=req.preview, started=time.time())
        executor.submit(jobs.run_job, str(store.root), job_id, key, backend_factory,
                        req.provider)
        return public(store.read(job_id))

    @app.get("/api/jobs/{job_id}/download")
    def download(job_id: str):
        job = get_job(job_id)
        out = store.dir(job_id) / "output.pdf"
        if job["state"] != "done" or not out.exists():
            raise HTTPException(409, "The translation is not finished.")
        stem = Path(job["filename"]).stem or "book"
        return FileResponse(out, media_type="application/pdf",
                            filename=f"{stem}_bilingual.pdf",
                            headers={"Cache-Control": "no-store"})

    @app.delete("/api/jobs/{job_id}")
    def delete(job_id: str):
        job = get_job(job_id)
        if job["state"] in ACTIVE:
            raise HTTPException(409, "Wait for the job to finish before deleting it.")
        store.delete(job_id)
        return {"deleted": True}

    return app
