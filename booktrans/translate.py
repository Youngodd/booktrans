"""Translate page text through an LLM backend, with an on-disk cache."""
import re

from .backends.base import BackendError, complete
from . import glossary as gloss
from .languages import DEFAULT_TARGET
from .layout import KEEP
from .fsutil import read_json, write_json
from .prompts import layout_prompt, system_prompt

def load_cache(path):
    return read_json(path)


def save_cache(path, cache):
    write_json(path, cache)  # resumable


def with_glossary(system, glossary, text):
    """`system` plus the glossary entries that occur in `text`."""
    extra = gloss.note(glossary, text)
    return system + "\n\n" + extra if extra else system


def glossary_used(glossary, text):
    """{term: rendering} of the glossary entries a request for `text` carries."""
    return {t: zh for t, zh in (glossary or {}).items() if zh and gloss.mentioned(t, text)}


def source_text(text, blocks=None):
    """What a page's translation was made from: its blocks' text in layout mode, else its text."""
    return " ".join(b["text"] for b in blocks) if blocks else text


def is_stale(used, key, glossary, text):
    """True if page `key`, translated earlier, should be translated again because a glossary
    entry it mentions has since been changed, added or removed. `used` records, for each page
    translated since this was tracked, the entries it was translated with; for an older page
    nothing is recorded, so any entry it mentions counts as possibly changed."""
    now = glossary_used(glossary, text)
    return now != used[key] if key in used else bool(now)


def stale_positions(idx, pages, layout, cache, used, glossary, target):
    """Positions n (in idx) of the cached pages that a changed glossary affects."""
    out = []
    for n, (i, text) in enumerate(zip(idx, pages)):
        blocks = layout.get(n)
        key = cache_key(i, target, layout=blocks is not None)
        if key in cache and is_stale(used, key, glossary, source_text(text, blocks)):
            out.append(n)
    return out


def cache_key(i, target, layout=False):
    """Cache key of page i. Chinese (Simplified) keeps the plain keys of earlier versions;
    every other target has its own, so switching the target never reuses a translation."""
    key = ("L" if layout else "") + str(i)
    return key if target == DEFAULT_TARGET else f"{target}:{key}"


class EmptyReply(BackendError):
    """The model answered a request that had text in it with nothing."""


def translate(backend, text, glossary=None, source="en", target=DEFAULT_TARGET):
    if not text.strip():
        return ""
    system = with_glossary(system_prompt(source, target), glossary, text)
    for _ in range(2):  # an empty answer is cached like a real one, so never accept it
        out = complete(backend, system, text, 4096)
        if out.strip():
            return out
    raise EmptyReply("The model returned an empty translation. Press Continue to try again.")


def translate_blocks(backend, blocks, ctx=("", ""), glossary=None, source="en", target=DEFAULT_TARGET,
                     marks=False):
    """Translate a page's blocks in one request; falls back to one by one. Bold marks (**) a
    model adds are removed, unless the text is Markdown (`marks`), where they are the book's."""
    def tidy(s):
        return (s if marks else s.replace("**", "")).strip()

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
            return [tidy(got[n]) or KEEP for n in range(1, len(blocks) + 1)]
    out = []
    for b in blocks:
        try:
            out.append(tidy(translate(backend, b["text"], glossary, source, target)) or KEEP)
        except EmptyReply:
            out.append(KEEP)  # nothing came back: leave the original in place, do not erase it
    return out


def translate_all(backend, idx, pages, layout, ctx, cache, cache_path, redo=(), progress=None,
                  glossary=None, source="en", target=DEFAULT_TARGET, *, used=None, used_path=None,
                  refresh=False):
    """Translate every page (cached); returns flat-page translations by position.

    Layout pages are cached under "L<page>" and return "" here, since they are
    redrawn from the cache by render_layout_page.

    `used` ({page key: entries it was translated with}, saved at `used_path`) is kept up to
    date; with refresh=True a cached page is translated again when the glossary entries it
    mentions differ from the ones it was translated with.
    """
    def remember(key, text):
        if used is not None:
            used[key] = glossary_used(glossary, text)
            if used_path:
                save_cache(used_path, used)

    translations = []
    for n, (i, text) in enumerate(zip(idx, pages), 1):
        key = cache_key(i, target)
        if n - 1 in layout:
            key = cache_key(i, target, layout=True)
            blocks = layout[n - 1]
            if key not in cache or i in redo or len(cache[key]) != len(blocks) or \
                    (refresh and is_stale(used or {}, key, glossary, source_text(text, blocks))):
                print(f"Translating page {i + 1} ({n}/{len(pages)})...", flush=True)
                cache[key] = translate_blocks(backend, blocks, ctx[n - 1], glossary, source, target)
                save_cache(cache_path, cache)
                remember(key, source_text(text, blocks))
            translations.append("")
            if progress:
                progress("translate", n, len(pages))
            continue
        if key not in cache or i in redo or (refresh and is_stale(used or {}, key, glossary, text)):
            print(f"Translating page {i + 1} ({n}/{len(pages)})...", flush=True)
            cache[key] = translate(backend, text, glossary, source, target)
            save_cache(cache_path, cache)
            remember(key, text)
        translations.append(cache[key])
        if progress:
            progress("translate", n, len(pages))
    return translations


def unit_key(u, target):
    """Cache key of unit u of a book read as blocks (blocks.units)."""
    return f"B{u}" if target == DEFAULT_TARGET else f"{target}:B{u}"


def unit_cached(cache, key, unit):
    """True if the cache holds the translation of exactly this unit's text."""
    hit = cache.get(key)
    src = [text for _, _, text in unit]
    return isinstance(hit, dict) and hit.get("src") == src and len(hit.get("tr") or []) == len(src)


def translate_units(backend, blocks, all_units, chosen, cache, cache_path, redo=(), progress=None,
                    glossary=None, source="en", target=DEFAULT_TARGET, *, used=None, used_path=None,
                    refresh=False, marks=False):
    """Translate the units `chosen` (positions in `all_units`) of a book read as blocks and put
    the translations into the blocks.

    A unit is cached under "B<n>" as {"src": its texts, "tr": their translations}: the original
    and the translation are kept together, and a unit whose text has changed is translated
    again. The glossary bookkeeping (`used`, `refresh`) is that of translate_all.
    """
    from .blocks import apply, unit_text
    for n, u in enumerate(chosen, 1):
        unit = all_units[u]
        key = unit_key(u, target)
        text = unit_text(unit)
        if not unit_cached(cache, key, unit) or u in redo or \
                (refresh and is_stale(used or {}, key, glossary, text)):
            print(f"Translating part {u + 1} ({n}/{len(chosen)})...", flush=True)
            before = unit_text(all_units[u - 1])[-600:] if u > 0 else ""
            after = unit_text(all_units[u + 1])[:400] if u + 1 < len(all_units) else ""
            tr = translate_blocks(backend, [{"text": t} for _, _, t in unit], (before, after),
                                  glossary, source, target, marks=marks)
            cache[key] = {"src": [t for _, _, t in unit], "tr": tr}
            save_cache(cache_path, cache)
            if used is not None:
                used[key] = glossary_used(glossary, text)
                if used_path:
                    save_cache(used_path, used)
        apply(blocks, unit, cache[key]["tr"])
        if progress:
            progress("translate", n, len(chosen))
