"""The web service: upload a book, start a translation with your own API key, download."""
import asyncio
import os
import secrets
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..pipeline import total_pages
from ..readers import parse_range
from . import auth, jobs, mailer, wxcloud
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
    email: str = ""


class StorageUpload(BaseModel):
    file_id: str
    filename: str


class LoginRequest(BaseModel):
    code: str


def _setting(value, env, default):
    """An explicit argument wins, then the environment variable, then the default."""
    return value if value is not None else int(os.environ.get(env, default))


def create_app(data_dir=None, *, executor=None, backend_factory=jobs.default_backend,
               max_upload_mb=None, max_pages=None, retention_hours=None, secret=None,
               openid_lookup=auth.wechat_openid, send_mail=mailer.send_pdf, cloud=wxcloud):
    """Build the app. `executor` runs jobs (default: a pool of worker processes).

    Mini program users log in with `POST /api/login` and send the returned token as
    `Authorization: Bearer ...`; their jobs are private to them. Requests without a token
    (the web page) keep working on jobs that have no owner. `secret` signs the tokens
    (default: BOOKTRANS_SECRET). Finished jobs can be emailed with `send_mail`.

    Limits come from the arguments, else BOOKTRANS_MAX_UPLOAD_MB (60),
    BOOKTRANS_MAX_PAGES (400) and BOOKTRANS_RETENTION_HOURS (24).
    """
    max_upload_mb = _setting(max_upload_mb, "BOOKTRANS_MAX_UPLOAD_MB", 60)
    max_pages = _setting(max_pages, "BOOKTRANS_MAX_PAGES", 400)
    retention_hours = _setting(retention_hours, "BOOKTRANS_RETENTION_HOURS", 24)
    data_dir = data_dir or os.environ.get("BOOKTRANS_DATA", "data")
    store = JobStore(Path(data_dir) / "jobs")
    executor = executor or ProcessPoolExecutor(int(os.environ.get("BOOKTRANS_WORKERS", "2")))
    secret = secret or os.environ.get("BOOKTRANS_SECRET") or secrets.token_hex(32)
    app = FastAPI(title="Book translator", docs_url=None, redoc_url=None)
    app.state.store = store

    def drop_stored_result(job):
        """An expired job's finished PDF also lives in cloud storage; remove it there too."""
        if job.get("result_file_id"):
            cloud.delete(job.get("env") or os.environ.get("WX_CLOUD_ENV", ""),
                         [job["result_file_id"]])

    @app.on_event("startup")
    async def _cleanup():
        """Delete expired jobs now and then every hour while the server runs."""
        def sweep():
            store.cleanup(retention_hours * 3600, drop_stored_result)

        sweep()

        async def hourly():
            while True:
                await asyncio.sleep(3600)
                await asyncio.to_thread(sweep)
        app.state.cleanup_task = asyncio.create_task(hourly())

    trust_wx = os.environ.get("BOOKTRANS_TRUST_WX_HEADERS") == "1"

    def who(authorization: str = Header(None), x_wx_openid: str = Header(None)):
        """The caller's openid: from the header Cloud Hosting adds (only when trusted, i.e.
        the service is not reachable from the public internet), else from a login token."""
        if trust_wx and x_wx_openid:
            return x_wx_openid
        scheme, _, token = (authorization or "").partition(" ")
        return auth.read_token(secret, token) if scheme.lower() == "bearer" else None

    def get_job(job_id, viewer=None):
        job = store.read(job_id)
        if job is not None and job.get("owner") and job["owner"] != viewer:
            job = None  # someone else's job looks the same as a missing one
        if job is None:
            raise HTTPException(404, "Unknown job (it may have been deleted).")
        return job

    def public(job):
        keys = ("id", "filename", "state", "stage", "done", "total", "error", "pages_total",
                "range", "preview", "usage", "email_state")
        return {k: job[k] for k in keys if k in job} | {"est_cost_per_page": EST_COST_PER_PAGE}

    @app.post("/api/login")
    def login(req: LoginRequest):
        try:
            openid = openid_lookup(req.code)
        except auth.LoginError as e:
            raise HTTPException(401, str(e))
        return {"token": auth.make_token(secret, openid), "email_enabled": mailer.configured()}

    @app.get("/api/config")
    def config():
        return {"email_enabled": mailer.configured()}

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})

    @app.post("/api/jobs")
    async def upload(file: UploadFile = File(...), viewer: str = Depends(who)):
        ext = Path(file.filename or "").suffix.lower()
        if ext not in EXTENSIONS:
            raise HTTPException(400, "Upload a .pdf, .epub or .txt file.")
        job_id = store.new(file.filename, ocr=False, range="", pages_total=0,
                           owner=viewer or "")
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
    def status(job_id: str, viewer: str = Depends(who)):
        return public(get_job(job_id, viewer))

    @app.post("/api/jobs/{job_id}/start")
    def start(job_id: str, req: StartRequest, viewer: str = Depends(who)):
        job = get_job(job_id, viewer)
        if job["state"] in ACTIVE:
            raise HTTPException(409, "This job is already running.")
        key = req.api_key.strip()
        if req.provider not in WEB_PROVIDERS:
            raise HTTPException(400, "Unknown provider.")
        if len(key) < 8 or (req.provider == "api" and not key.startswith("sk-")):
            raise HTTPException(400, "Enter your API key for the chosen provider.")
        email = req.email.strip()
        if email and not mailer.EMAIL_RE.match(email):
            raise HTTPException(400, "That email address does not look right.")
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
                    range=rng, preview=req.preview, started=time.time(), email=email,
                    email_state="")
        executor.submit(jobs.run_job, str(store.root), job_id, key, backend_factory,
                        req.provider, send_mail if email else None)
        return public(store.read(job_id))

    def cloud_env(request):
        env = request.headers.get("x-wx-env") or os.environ.get("WX_CLOUD_ENV")
        if not env:
            raise HTTPException(400, "Cloud storage is not available here.")
        return env

    @app.post("/api/jobs/from-storage")
    def upload_from_storage(req: StorageUpload, request: Request, viewer: str = Depends(who)):
        """Create a job from a book the mini program put in cloud storage."""
        env = cloud_env(request)
        ext = Path(req.filename).suffix.lower()
        if ext not in EXTENSIONS:
            raise HTTPException(400, "Upload a .pdf, .epub or .txt file.")
        job_id = store.new(req.filename, ocr=False, range="", pages_total=0, owner=viewer or "")
        path = store.dir(job_id) / ("input" + ext)
        try:
            cloud.download(env, req.file_id, path, max_upload_mb << 20)
        except cloud.CloudError as e:
            store.delete(job_id)
            if "too large" in str(e):
                raise HTTPException(413, f"The file is larger than {max_upload_mb} MB.")
            raise HTTPException(400, "The uploaded file could not be fetched.")
        cloud.delete(env, [req.file_id])  # the book now lives only in the job folder
        try:
            n = total_pages(path)
        except Exception:
            store.delete(job_id)
            raise HTTPException(400, "This file could not be read as a book.")
        store.write(job_id, pages_total=n)
        return public(store.read(job_id))

    @app.get("/api/jobs/{job_id}/result")
    def result(job_id: str, request: Request, viewer: str = Depends(who)):
        """Put the finished PDF in cloud storage and return its file id for wx.cloud.downloadFile."""
        job = get_job(job_id, viewer)
        out = store.dir(job_id) / "output.pdf"
        if job["state"] != "done" or not out.exists():
            raise HTTPException(409, "The translation is not finished.")
        env = cloud_env(request)
        if not job.get("result_file_id"):
            try:
                file_id = cloud.upload(env, out, f"results/{job_id}.pdf")
            except cloud.CloudError:
                raise HTTPException(502, "Could not store the finished PDF. Try again.")
            store.write(job_id, result_file_id=file_id, env=env)
            job["result_file_id"] = file_id
        stem = Path(job["filename"]).stem or "book"
        return {"file_id": job["result_file_id"], "filename": f"{stem}_bilingual.pdf"}

    @app.get("/api/jobs/{job_id}/download")
    def download(job_id: str, viewer: str = Depends(who)):
        job = get_job(job_id, viewer)
        out = store.dir(job_id) / "output.pdf"
        if job["state"] != "done" or not out.exists():
            raise HTTPException(409, "The translation is not finished.")
        stem = Path(job["filename"]).stem or "book"
        return FileResponse(out, media_type="application/pdf",
                            filename=f"{stem}_bilingual.pdf",
                            headers={"Cache-Control": "no-store"})

    @app.delete("/api/jobs/{job_id}")
    def delete(job_id: str, viewer: str = Depends(who)):
        job = get_job(job_id, viewer)
        if job["state"] in ACTIVE:
            raise HTTPException(409, "Wait for the job to finish before deleting it.")
        drop_stored_result(job)
        store.delete(job_id)
        return {"deleted": True}

    return app
