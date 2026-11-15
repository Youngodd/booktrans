"""What to tell the user when something goes wrong, shared by the command line, the web service and
the desktop app: the kind of failure, what to do about it, the key blanked out of everything written,
what the program was working on, and a log file for the full details.

This module imports nothing from the rest of the package at load time (the backends import it).
"""
import contextlib
import contextvars
import datetime
import errno
import os
import re
import sys
import traceback
from pathlib import Path

# What the user can do about each kind of failure (the web pages show a translated version, keyed by code).
FAILURE_ADVICE = {
    "auth": "The provider refused the request. Check the key, that the account has credit, and that it may use this model.",
    "quota": "The account is out of credit or over its quota. Top it up, then press Continue.",
    "rate_limit": "The provider is limiting requests. Wait a minute, then press Continue.",
    "timeout": "The provider took too long to answer. Press Continue to retry.",
    "network": "Could not reach the provider. Check your internet connection, then press Continue.",
    "server": "The provider had a problem on its side. Try Continue again in a few minutes.",
    "provider": "The provider returned an error. Press Continue to retry; if it repeats, the detail below says why.",
    "disk": "The app could not write its files (disk full or no permission). Free some space, then press Continue.",
    "memory": "The computer ran out of memory on this book. Close other apps, or translate a smaller page range.",
    "input": "This book or one of the settings could not be used.",
    "unknown": "An unexpected error stopped the translation. Press Continue to retry; the log has the full details.",
}

# The same for the command line, which has no Continue button.
CLI_ADVICE = {
    "auth": "The provider refused the request. Check the API key, that the account has credit, and that it may use this model.",
    "quota": "The account is out of credit or over its quota. Top it up, then run the same command again.",
    "rate_limit": "The provider is limiting requests. Wait a minute, then run the same command again.",
    "timeout": "The provider took too long to answer. Run the same command again to retry.",
    "network": "Could not reach the provider. Check your internet connection and proxy settings, then run the same command again.",
    "server": "The provider had a problem on its side. Run the same command again in a few minutes.",
    "provider": "The provider returned an error. Run the same command again to retry; if it repeats, the message above says why.",
    "disk": "The program could not write its files (disk full or no permission). Free some space or choose another -o folder, then run the same command again.",
    "memory": "The computer ran out of memory on this book. Close other programs, or translate a smaller page range (--pages).",
    "input": "This book or one of the options could not be used.",
    "unknown": "An unexpected error stopped the run. The log file has the full details.",
}

# Why a call failed, in a few words, for the retry notice.
SHORT_CAUSE = {"auth": "key refused", "quota": "out of credit", "rate_limit": "rate limit", "timeout": "timed out",
               "network": "network error", "server": "provider server error", "provider": "provider error",
               "disk": "disk error", "memory": "out of memory", "input": "bad input", "unknown": "error"}

KEY_ENV = ("ANTHROPIC_API_KEY", "DASHSCOPE_API_KEY", "DEEPSEEK_API_KEY", "BOOKTRANS_API_KEY", "OPENAI_API_KEY")
_KEY_SHAPE = re.compile(r"\b(?:sk|key|api)[-_][A-Za-z0-9_-]{12,}\b")  # something that looks like a key
MAX_LOG_BYTES = 1 << 20


# ---------------------------------------------------------------- secrets

def redact(text, secrets=()):
    """`text` with every given secret, the keys in the environment, and anything shaped like an
    API key replaced by ***."""
    text = str(text)
    known = [s for s in (*secrets, *(os.environ.get(n) for n in KEY_ENV)) if s and len(s) >= 6]
    for s in sorted(set(known), key=len, reverse=True):
        text = text.replace(s, "***")
    return _KEY_SHAPE.sub("***", text)


# ---------------------------------------------------------------- what the program was working on

_working = contextvars.ContextVar("booktrans_working_on", default={})


@contextlib.contextmanager
def working_on(**fields):
    """Say what is being done, so a failure inside names it: `with working_on(stage="translate",
    page=12): ...`. Nests; the inner fields add to or replace the outer ones."""
    token = _working.set({**_working.get(), **{k: v for k, v in fields.items() if v not in (None, "")}})
    try:
        yield
    except BaseException as e:
        if not hasattr(e, "booktrans_task"):  # the innermost task is the most exact: keep it on the error
            try:
                e.booktrans_task = where()
            except AttributeError:  # an exception type that takes no new attributes
                pass
        raise
    finally:
        _working.reset(token)


def where():
    """The current task as a short phrase: "translating page 12", "reading page 3 (OCR)", or "" ."""
    w = _working.get()
    verbs = {"translate": "translating", "ocr": "reading (OCR)", "glossary": "collecting names",
             "read": "reading the book", "render": "writing the output file"}
    stage = verbs.get(w.get("stage"), w.get("stage") or "")
    unit = w.get("unit", "page")
    return " ".join(str(x) for x in (stage, f"{unit} {w['page']}" if w.get("page") is not None else "") if x)


def task_of(e):
    """What was being done when `e` was raised ("translating page 12"), or "" when unknown."""
    return getattr(e, "booktrans_task", "") or where()


# ---------------------------------------------------------------- classifying

def _is(e, name):
    """True if `e` is, or is a subclass of, the class called `name` (by name, so this module need not
    import the backends, which import it)."""
    return any(c.__name__ == name for c in type(e).__mro__)


def classify(e):
    """A failure code (a key of FAILURE_ADVICE) from the exception and what caused it."""
    chain = []
    x = e
    while x is not None and len(chain) < 6:
        chain.append(x)
        x = x.__cause__ or x.__context__
    names = " ".join(type(c).__name__ for c in chain)
    status = next((getattr(c, "status_code", None) for c in chain if isinstance(getattr(c, "status_code", None), int)), 0)
    said = str(e).lower()
    if _is(e, "AuthError"):
        return "auth"
    if any(w in said for w in ("credit balance", "insufficient", "arrearage", "quota", "billing")):
        return "quota"
    if status == 429 or "RateLimit" in names or "rate limit" in said:
        return "rate_limit"
    if "Timeout" in names or "timed out" in said:
        return "timeout"
    if status >= 500 or "InternalServer" in names or "Overloaded" in names:
        return "server"
    if "Connect" in names or "gaierror" in names or "ProxyError" in names or "SSL" in names or "connection" in said:
        return "network"
    if any(isinstance(c, MemoryError) for c in chain):
        return "memory"
    if any(isinstance(c, OSError) and c.errno in (errno.ENOSPC, errno.EACCES, errno.EPERM, errno.EROFS, errno.EDQUOT)
           for c in chain):
        return "disk"
    if _is(e, "BackendError"):
        return "provider"
    if isinstance(e, ValueError):
        return "input"
    return "unknown"


def detail_of(e, secrets=(), limit=400, verbose=True):
    """A short, safe description: the message of errors this program raises itself, otherwise the
    type name. With `verbose` (the command line: the user owns the machine) it also gives the
    message and file of other errors; the web service passes False so that nothing about the
    server's files or internals reaches a browser."""
    if _is(e, "BackendError") or isinstance(e, ValueError):
        text = str(e)
    elif isinstance(e, OSError) and e.strerror:
        text = e.strerror + (f": {e.filename}" if verbose and e.filename else "")
    elif verbose and str(e) and not isinstance(e, (KeyError, AssertionError)):
        text = f"{type(e).__name__}: {e}"
    else:
        text = type(e).__name__
    return redact(text, secrets)[:limit]


def format_exception(e, secrets=()):
    """The full traceback as text, with the keys blanked out."""
    return redact("".join(traceback.format_exception(type(e), e, e.__traceback__)), secrets)


# ---------------------------------------------------------------- the log file

def log_path():
    """Where the details go: $BOOKTRANS_LOG, else ~/.booktrans/error.log."""
    given = os.environ.get("BOOKTRANS_LOG")
    if given:
        return Path(given)
    try:
        home = Path.home()
    except (RuntimeError, KeyError):  # no home folder known (a service account)
        import tempfile
        home = Path(tempfile.gettempdir())
    return home / ".booktrans" / "error.log"


def write_log(text):
    """Append to the log file (it is cut when it passes 1 MB). Returns the path, or None when it
    could not be written: a log must never be the thing that fails."""
    path = log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > MAX_LOG_BYTES:
            path.write_text("", encoding="utf-8")
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"[{stamp}] {redact(text)}\n")
        return path
    except OSError:
        return None


def log_failure(e, command="", secrets=()):
    """Write the traceback, the task and the command to the log file; returns the path or None."""
    task = task_of(e)
    head = "Failure" + (f" while {task}" if task else "") + (f"\n  command: {command}" if command else "")
    return write_log(head + "\n" + format_exception(e, secrets))


def warn(message):
    """Tell the user about something that went wrong but did not stop the run (a picture left
    out, a damaged cache file ignored). Goes to the screen (stderr) and the log file."""
    message = redact(message)
    print(f"Warning: {message}", file=sys.stderr, flush=True)
    write_log("Warning: " + message)


def note(message, exc=None):
    """Record in the log file only a failure that was handled and does not matter to the user
    (an optional step that did not work): so it can be found when something looks wrong."""
    write_log("Note: " + message + (("\n" + format_exception(exc)) if exc is not None else ""))


# ---------------------------------------------------------------- the command line's report

def report(e, *, command="", debug=False, resumable=True, book=""):
    """The text the command line prints for a failure that is not a plain input error: one classified
    line saying what was being done and why it failed, what to do about it, and where the log is.
    Writes the log; with debug it also prints the traceback."""
    code = classify(e)
    path = log_failure(e, command)
    task = task_of(e)
    detail = detail_of(e)
    said = detail.lower().startswith(task.lower()) if task else True  # complete() already names the task
    lines = [f"Error: {detail}" if said else f"Error while {task}: {detail}"]
    if book:
        lines.append(f"Book: {book}")
    lines.append(CLI_ADVICE[code])
    if resumable and code != "input":
        lines.append("Progress is saved; run the same command again to resume.")
    lines.append(f"Details: {path}" if path else "Details: (the log file could not be written; run with --debug to see them)")
    if debug:
        lines.append("\n" + format_exception(e))
    return "\n".join(lines)
