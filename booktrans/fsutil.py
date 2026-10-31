"""Small file helpers shared by the cache, glossary, OCR and spend files."""
import json
import os


def write_json(path, data, **kw):
    """Write `data` as JSON so a crash or a killed worker never leaves half a file: the
    new content goes to a temporary file that then replaces the old one."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, **kw), encoding="utf-8")
    os.replace(tmp, path)


def read_json(path):
    """The JSON object in `path`, or {} when there is no file or it cannot be read."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}
