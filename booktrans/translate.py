"""Translate page text through an LLM backend, with an on-disk cache."""
import json
import re

from .prompts import LAYOUT_PROMPT, SYSTEM_PROMPT


def load_cache(path):
    return json.loads(path.read_text()) if path.exists() else {}


def save_cache(path, cache):
    path.write_text(json.dumps(cache, ensure_ascii=False))  # resumable


def translate(backend, text):
    if not text.strip():
        return ""
    return backend.complete(SYSTEM_PROMPT, text, max_tokens=4096)


def translate_blocks(backend, blocks, ctx=("", "")):
    """Translate a page's blocks in one request; falls back to one by one."""
    src = "\n".join("[%d] %s" % (n, b["text"]) for n, b in enumerate(blocks, 1))
    before, after = ctx
    if before:
        src = "Context, end of the previous page (do not translate):\n%s\n\nBlocks to translate:\n%s" % (before, src)
    if after:
        src += "\n\nContext, start of the next page (do not translate):\n" + after
    for _ in range(2):
        out = backend.complete(LAYOUT_PROMPT, src, max_tokens=8192)
        parts = re.split(r"(?m)^\[(\d+)\][ \t]*", out)  # ['', '1', 'txt', '2', ...]
        got = {int(parts[k]): parts[k + 1].strip() for k in range(1, len(parts) - 1, 2)}
        if sorted(got) == list(range(1, len(blocks) + 1)):
            return [got[n].replace("**", "") for n in range(1, len(blocks) + 1)]
    return [translate(backend, b["text"]).replace("**", "") for b in blocks]


def translate_all(backend, idx, pages, layout, ctx, cache, cache_path, redo=()):
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
            continue
        if key not in cache or i in redo:
            print(f"Translating page {i + 1} ({n}/{len(pages)})...", flush=True)
            cache[key] = translate(backend, text)
            save_cache(cache_path, cache)
        translations.append(cache[key])
    return translations
