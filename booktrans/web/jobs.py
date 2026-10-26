"""Job storage and the worker function of the web service.

A job is a folder under the data directory: the uploaded book, its output, the
translation cache and job.json (the state shown to the browser). The folder name
is a random id that acts as the access token. API keys are only passed to the
worker in memory; they are never written to disk.
"""
import json
import os
import re
import secrets
import shutil
import time
from pathlib import Path

from ..backends.base import BackendError

ID_RE = re.compile(r"^[A-Za-z0-9_-]{22}$")
SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]")
PREVIEW_PAGES = 3


class JobStore:
    def __init__(self, root, keep_names=False):
        self.root = Path(root)
        self.keep_names = keep_names  # desktop: keep the original (e.g. Chinese) file name
        self.root.mkdir(parents=True, exist_ok=True)

    def new(self, filename, **fields):
        job_id = secrets.token_urlsafe(16)  # 22 characters
        (self.root / job_id).mkdir()
        ext = Path(filename).suffix.lower()
        name = Path(filename).name if self.keep_names else SAFE_NAME.sub("_", Path(filename).name)
        self.write(job_id, id=job_id, filename=name[:120],
                   ext=ext, state="uploaded", stage="", done=0, total=0, error="",
                   created=time.time(), **fields)
        return job_id

    def dir(self, job_id):
        """The job's folder, or None for an unknown or malformed id."""
        if not isinstance(job_id, str) or not ID_RE.match(job_id):
            return None
        path = self.root / job_id
        return path if path.is_dir() else None

    def read(self, job_id):
        path = self.dir(job_id)
        try:
            return json.loads((path / "job.json").read_text(encoding="utf-8")) if path else None
        except (OSError, ValueError):
            return None

    def write(self, job_id, **fields):
        """Merge fields into job.json (atomically, so readers never see half a file)."""
        path = self.root / job_id
        job = {}
        if (path / "job.json").exists():
            job = json.loads((path / "job.json").read_text(encoding="utf-8"))
        job.update(fields)
        tmp = path / "job.json.tmp"
        tmp.write_text(json.dumps(job), encoding="utf-8")
        for attempt in range(50):  # Windows refuses to replace a file a reader has open
            try:
                os.replace(tmp, path / "job.json")
                break
            except PermissionError:
                if attempt == 49:
                    raise
                time.sleep(0.02)

    def delete(self, job_id):
        path = self.dir(job_id)
        if path:
            shutil.rmtree(path, ignore_errors=True)

    def reset_interrupted(self):
        """Mark jobs left queued/running by a closed app as paused; returns how many."""
        n = 0
        for path in self.root.iterdir():
            job = self.read(path.name) if path.is_dir() else None
            if job and job.get("state") in ("queued", "running"):
                self.write(path.name, state="paused", stage="", error="")
                (path / "cancel").unlink(missing_ok=True)
                n += 1
        return n

    def cleanup(self, max_age_s, on_expire=None):
        """Delete jobs not touched for max_age_s seconds; returns how many.

        on_expire(job) is called with each job's data just before its folder is removed.
        """
        now, removed = time.time(), 0
        for path in self.root.iterdir():
            if path.is_dir() and ID_RE.match(path.name):
                newest = max((p.stat().st_mtime for p in path.iterdir()), default=0)
                if now - newest > max_age_s:
                    if on_expire:
                        on_expire(self.read(path.name) or {})
                    shutil.rmtree(path, ignore_errors=True)
                    removed += 1
        return removed


def default_backend(api_key, provider="api"):
    from ..backends import make_backend
    return make_backend(provider, api_key=api_key)


def preview_range(pages, total):
    """The first PREVIEW_PAGES pages of the chosen range, as a "start-end" string."""
    from ..readers import parse_range
    idx = parse_range(pages, total)
    return f"{idx[0] + 1}-{idx[min(PREVIEW_PAGES, len(idx)) - 1] + 1}"


def _failure_text(e, api_key):
    msg = str(e).replace(api_key, "***") if api_key else str(e)
    if not isinstance(e, (BackendError, ValueError)):
        msg = "Something went wrong while translating this book."
    return msg[:500]


def run_glossary_draft(root, job_id, api_key, backend_factory=default_backend, provider="api",
                       pages=""):
    """Build the book's glossary ahead of the translation so the user can review it."""
    from ..pipeline import draft_glossary
    from ..spend import Meter, SpendLimitReached
    store = JobStore(root)
    job = store.read(job_id)
    if job is None:
        return
    path = store.dir(job_id)
    store.write(job_id, glossary_state="building", glossary_error="")
    try:
        translator = backend_factory(api_key, provider)
        meter = Meter(job.get("spend_limit", 0), path / "output.spend.json")
        glossary = draft_glossary(path / ("input" + job["ext"]), translator,
                                  path / "output.glossary.json", pages=pages or None, meter=meter)
        store.write(job_id, glossary_state="ready", spent_cny=round(meter.spent, 4),
                    glossary_count=sum(1 for zh in glossary.values() if zh))
    except SpendLimitReached as e:
        store.write(job_id, glossary_state="failed", spent_cny=round(e.spent, 4),
                    glossary_error=f"Spend limit reached (¥{e.spent:.2f} of ¥{e.limit:.2f}). "
                                   "Raise the limit or skip the name review.")
    except BaseException as e:
        store.write(job_id, glossary_state="failed", glossary_error=_failure_text(e, api_key))
        if not isinstance(e, Exception):
            raise


def run_job(root, job_id, api_key, backend_factory=default_backend, provider="api",
            send_mail=None):
    """Run one job to the end. Executed in a worker process (or thread, in tests)."""
    from ..pipeline import Cancelled, translate_book
    from ..spend import Meter, NoCalls, SpendLimitReached, rest_estimate
    store = JobStore(root)
    job = store.read(job_id)
    if job is None:
        return
    path = store.dir(job_id)

    last = {"stage": "", "done": 0, "total": 0}

    def progress(stage, done, total):
        if (path / "cancel").exists():  # set by the desktop app's Cancel button
            raise Cancelled()
        last.update(stage=stage, done=done, total=total)
        store.write(job_id, state="running", stage=stage, done=done, total=total)

    meter = Meter(job.get("spend_limit", 0), path / "output.spend.json")  # 0: counts, never stops
    translator = None
    try:
        store.write(job_id, state="running", stage="scan", done=0, total=0, error="")
        translator = NoCalls() if job.get("only_cached") else backend_factory(api_key, provider)
        pages = job["range"]
        translate_book(path / ("input" + job["ext"]), path / "output.pdf", translator,
                       ocr_backend=translator if job["ocr"] else None, pages=pages,
                       progress=progress, auto_glossary=job.get("auto_glossary", True),
                       meter=meter, only_cached=job.get("only_cached", False))
        store.write(job_id, state="done", stage="done", usage=translator.usage.as_dict(),
                    finished=time.time(), spent_cny=round(meter.spent, 4),
                    partial=bool(job.get("only_cached", False)))
        if send_mail and job.get("email"):
            try:
                stem = Path(job["filename"]).stem or "book"
                send_mail(job["email"], path / "output.pdf", f"{stem}_bilingual.pdf")
                store.write(job_id, email_state="sent")
            except Exception:  # the PDF is still downloadable; just record the failure
                store.write(job_id, email_state="failed")
    except SpendLimitReached as e:  # the translated pages are cached; the user decides what next
        rest = rest_estimate(e.spent, last["done"], last["total"]) if last["stage"] == "translate" else None
        store.write(job_id, state="needs_decision", spent_cny=round(e.spent, 4), est_rest_cny=rest,
                    usage=translator.usage.as_dict() if translator else {})
    except Cancelled:  # finished pages stay in the cache; Start continues from there
        (path / "cancel").unlink(missing_ok=True)
        store.write(job_id, state="paused", stage="", spent_cny=round(meter.spent, 4),
                    usage=translator.usage.as_dict() if translator else {})
    except BaseException as e:  # report every failure to the browser, never lose the job
        usage = translator.usage.as_dict() if translator else {}
        store.write(job_id, state="failed", error=_failure_text(e, api_key), usage=usage,
                    finished=time.time(), spent_cny=round(meter.spent, 4))
        if not isinstance(e, Exception):
            raise
