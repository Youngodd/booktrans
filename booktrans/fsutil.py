"""Small file helpers shared by the cache, glossary, OCR and spend files."""
import json
import os
import threading


def write_json(path, data, **kw):
    """Write `data` as JSON so a crash or a killed worker never leaves half a file: the
    new content goes to a temporary file that then replaces the old one."""
    # one temporary name per process and thread: two runs on the same book at once must not share it
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, **kw), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def read_json(path):
    """The JSON object in `path`, or {} when there is no file or it cannot be read. A file that is
    there but damaged is said so: ignoring a cache means paying for those pages again."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        _damaged(path, e)
        return {}
    if not isinstance(data, dict):
        _damaged(path, "it does not hold a JSON object")
        return {}
    return data


def _damaged(path, why):
    from . import failure
    failure.warn(f"{path.name} could not be read ({why}) and is ignored; what it held will be done again.")
