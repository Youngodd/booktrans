"""Translate page text through an LLM backend, with an on-disk cache."""
import json
import re
import time

from .backends.base import AuthError, BackendError
from .prompts import LAYOUT_PROMPT, SYSTEM_PROMPT

RETRY_DELAYS = (5, 20, 60)  # seconds to wait before each retry of a failed call


def complete(backend, system, text, max_tokens):
    """backend.complete, retried when the call fails (dropped connection, rate limit)."""
    for delay in (*RETRY_DELAYS, None):
        try:
            return backend.complete(system, text, max_tokens=max_tokens)
        except AuthError:
            raise
        except BackendError:
            if delay is None:
                raise
            time.sleep(delay)


def load_cache(path):
    return json.loads(path.read_text()) if path.exists() else {}


def save_cache(path, cache):
    path.write_text(json.dumps(cache, ensure_ascii=False))  # resumable


def translate(backend, text):
    if not text.strip():
        return ""
    return complete(backend, SYSTEM_PROMPT, text, 4096)


def translate_blocks(backend, blocks, ctx=("", "")):
    """Translate a page's blocks in one request; falls back to one by one."""
    src = "\n".join("[%d] %s" % (n, b["text"]) for n, b in enumerate(blocks, 1))
    before, after = ctx
    if before:
        src = "Context, end of the previous page (do not translate):\n%s\n\nBlocks to translate:\n%s" % (before, src)
    if after:
        src += "\n\nContext, start of the next page (do not translate):\n" + after
    for _ in range(2):
        out = complete(backend, LAYOUT_PROMPT, src, 8192)
        parts = re.split(r"(?m)^\[(\d+)\][ \t]*", out)  # ['', '1', 'txt', '2', ...]
        got = {int(parts[k]): parts[k + 1].strip() for k in range(1, len(parts) - 1, 2)}
        if sorted(got) == list(range(1, len(blocks) + 1)):
            return [got[n].replace("**", "") for n in range(1, len(blocks) + 1)]
    return [translate(backend, b["text"]).replace("**", "") for b in blocks]


def translate_all(backend, idx, pages, layout, ctx, cache, cache_path, redo=(), progress=None):
    """Translate every page (cached); returns flat-page translations by position.

    Layout pages are cached under "L<page>" and return "" here, since they are
    redrawn from the cache by render_layout_page.
    """
    translations = []
    for n, (i, text) in enumerate(zip(idx, pages), 1):
        key = str(i)
        if n - 1 in layout:
            key = "L" + key
            if key not in cache or i in redo or len(cache[key]) != len(layout[n - 1]):
                print(f"Translating page {i + 1} ({n}/{len(pages)})...", flush=True)
                cache[key] = translate_blocks(backend, layout[n - 1], ctx[n - 1])
                save_cache(cache_path, cache)
            translations.append("")
            if progress:
                progress("translate", n, len(pages))
            continue
        if key not in cache or i in redo:
            print(f"Translating page {i + 1} ({n}/{len(pages)})...", flush=True)
            cache[key] = translate(backend, text)
            save_cache(cache_path, cache)
        translations.append(cache[key])
        if progress:
            progress("translate", n, len(pages))
    return translations
