"""Translate page text through an LLM backend, with an on-disk cache."""
import re
import time

from .backends.base import AuthError, BackendError
from . import glossary as gloss
from .languages import DEFAULT_TARGET
from .fsutil import read_json, write_json
from .prompts import layout_prompt, system_prompt

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
    return read_json(path)


def save_cache(path, cache):
    write_json(path, cache)  # resumable


def with_glossary(system, glossary, text):
    """`system` plus the glossary entries that occur in `text`."""
    extra = gloss.note(glossary, text)
    return system + "\n\n" + extra if extra else system


def cache_key(i, target, layout=False):
    """Cache key of page i. Chinese (Simplified) keeps the plain keys of earlier versions;
    every other target has its own, so switching the target never reuses a translation."""
    key = ("L" if layout else "") + str(i)
    return key if target == DEFAULT_TARGET else f"{target}:{key}"


def translate(backend, text, glossary=None, source="en", target=DEFAULT_TARGET):
    if not text.strip():
        return ""
    return complete(backend, with_glossary(system_prompt(source, target), glossary, text), text, 4096)


def translate_blocks(backend, blocks, ctx=("", ""), glossary=None, source="en", target=DEFAULT_TARGET):
    """Translate a page's blocks in one request; falls back to one by one."""
    src = "\n".join("[%d] %s" % (n, b["text"]) for n, b in enumerate(blocks, 1))
    before, after = ctx
    if before:
        src = "Context, end of the previous page (do not translate):\n%s\n\nBlocks to translate:\n%s" % (before, src)
    if after:
        src += "\n\nContext, start of the next page (do not translate):\n" + after
    system = with_glossary(layout_prompt(source, target), glossary, " ".join(b["text"] for b in blocks))
    for _ in range(2):
        out = complete(backend, system, src, 8192)
        parts = re.split(r"(?m)^\[(\d+)\][ \t]*", out)  # ['', '1', 'txt', '2', ...]
        got = {int(parts[k]): parts[k + 1].strip() for k in range(1, len(parts) - 1, 2)}
        if sorted(got) == list(range(1, len(blocks) + 1)):
            return [got[n].replace("**", "") for n in range(1, len(blocks) + 1)]
    return [translate(backend, b["text"], glossary, source, target).replace("**", "") for b in blocks]


def translate_all(backend, idx, pages, layout, ctx, cache, cache_path, redo=(), progress=None,
                  glossary=None, source="en", target=DEFAULT_TARGET):
    """Translate every page (cached); returns flat-page translations by position.

    Layout pages are cached under "L<page>" and return "" here, since they are
    redrawn from the cache by render_layout_page.
    """
    translations = []
    for n, (i, text) in enumerate(zip(idx, pages), 1):
        key = cache_key(i, target)
        if n - 1 in layout:
            key = cache_key(i, target, layout=True)
            if key not in cache or i in redo or len(cache[key]) != len(layout[n - 1]):
                print(f"Translating page {i + 1} ({n}/{len(pages)})...", flush=True)
                cache[key] = translate_blocks(backend, layout[n - 1], ctx[n - 1], glossary, source, target)
                save_cache(cache_path, cache)
            translations.append("")
            if progress:
                progress("translate", n, len(pages))
            continue
        if key not in cache or i in redo:
            print(f"Translating page {i + 1} ({n}/{len(pages)})...", flush=True)
            cache[key] = translate(backend, text, glossary, source, target)
            save_cache(cache_path, cache)
        translations.append(cache[key])
        if progress:
            progress("translate", n, len(pages))
    return translations
