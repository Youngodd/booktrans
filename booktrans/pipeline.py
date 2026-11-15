"""The whole job as a function: read a book, translate it, write the translated PDF.

Used by the command line (cli.py) and callable from other programs, such as a web
service. Nothing here prints or exits; progress goes to an optional callback.
"""
import os
import tempfile
from pathlib import Path

from . import blocks as blocks_mod
from . import glossary as glossary_mod
from . import failure, languages
from .layout import book_ratios, collect_layout, measure_layout_page, render_layout_page
from .ocr import ocr_scanned_pages
from .options import JobOptions
from .readers import open_pdf, parse_range, read_book
from .spend import Metered, NoCalls, SpendLimitReached
from .blockreaders import read_blocks
from .blockwriters import write_blocks
from .pdfblocks import pdf_blocks
from .translate import (cache_key, is_stale, load_cache, stale_positions, translate_all,
                        translate_units, unit_cached, unit_key)
from .writer import make_pdf

class Cancelled(Exception):
    """Raised by a `progress` callback to stop translate_book; the cache keeps finished pages."""


MIN_TEXT_CHARS = 20  # PDF pages with less text than this are treated as scans
BLOCK_INPUTS = (".docx", ".md", ".markdown")  # read as blocks only (blockreaders.py)
INPUTS = (".pdf", ".epub", ".txt") + BLOCK_INPUTS
MARKDOWN = (".md", ".markdown")


def assets_path(state):
    """The folder next to `state` that holds a book's pictures."""
    return Path(state).with_suffix(".assets")


def book_pages(book):
    """The text of each page of a book. A Word or Markdown file has no pages: its units of
    about a page stand in for them (blocks.units)."""
    book = Path(book)
    if book.suffix.lower() not in BLOCK_INPUTS:
        return read_book(book)
    with tempfile.TemporaryDirectory() as tmp:
        return [blocks_mod.unit_text(u) for u in blocks_mod.units(read_blocks(book, tmp))]


def reads_as_blocks(book, output_format="pdf"):
    """True if the job goes through the blocks of the book: every Word or Markdown file, and
    an EPUB or text file written as anything but PDF. (A PDF is translated page by page and
    turned into blocks afterwards; EPUB or text to PDF is the plain-text path of old.)"""
    ext = Path(book).suffix.lower()
    return ext in BLOCK_INPUTS or (ext != ".pdf" and output_format != "pdf")


def default_output(book, pages=None, mode="bilingual", target=languages.DEFAULT_TARGET, fmt="pdf"):
    """Where the result goes when no output path is given: `<book>_bilingual.pdf`, or
    `<book>_<target>.pdf` for a translation-only one (with the extension of the format)."""
    book = Path(book)
    suffix = " pages " + pages.replace(" ", "") if pages else ""
    tag = "bilingual" if mode == "bilingual" else target
    return book.with_name(f"{book.stem}_{tag}{suffix}.{fmt}")


def glossary_path(state, target=languages.DEFAULT_TARGET):
    """The glossary file next to `state`; renderings are per target language."""
    state = Path(state)
    if target == languages.DEFAULT_TARGET:
        return state.with_suffix(".glossary.json")
    return state.with_suffix(f".glossary.{target}.json")


def used_path(state):
    """The file that records, per translated page, the glossary entries it was translated with."""
    return Path(state).with_suffix(".glossary-used.json")


def glossary_changes(book, out, *, pages=None, flat=False, target=languages.DEFAULT_TARGET,
                     glossary_file=None, state=None):
    """The pages already translated that the glossary, as it is now, would change.

    Returns {"pages": [page numbers, 1-based], "translated": how many pages are cached}. Nothing
    is paid for and nothing is written: it compares each cached page's recorded glossary
    entries with the current glossary (`<state>.glossary.json`, plus `glossary_file`).
    """
    book, out = Path(book), Path(out)
    target = languages.check_target(target)
    state = Path(state) if state else out
    if book.suffix.lower() != ".pdf":  # a book translated as blocks has its units in the cache
        found = _unit_changes(book, state, pages, target, glossary_file)
        if found["translated"] or book.suffix.lower() in BLOCK_INPUTS:
            return found
    all_pages = read_book(book)
    idx = parse_range(pages, len(all_pages))
    texts = [all_pages[i] for i in idx]
    is_pdf = book.suffix.lower() == ".pdf"
    scanned = [n for n, t in enumerate(texts) if len(t.strip()) < MIN_TEXT_CHARS] if is_pdf else []
    ocr_cache = load_cache(state.with_suffix(".ocr.json"))
    for n in scanned:
        texts[n] = ocr_cache.get(str(idx[n]), texts[n])
    layout = {} if not is_pdf or flat else collect_layout(book, idx, skip=scanned)[0]
    glossary = glossary_mod.load(glossary_path(state, target))
    if glossary_file:
        glossary.update(glossary_mod.parse_file(glossary_file))
    cache = load_cache(state.with_suffix(".cache.json"))
    stale = stale_positions(idx, texts, layout, cache, load_cache(used_path(state)), glossary, target)
    translated = sum(1 for n, i in enumerate(idx)
                     if cache_key(i, target, layout=n in layout) in cache)
    return {"pages": [idx[n] + 1 for n in stale], "translated": translated}


def _unit_changes(book, state, pages, target, glossary_file):
    """glossary_changes for a book translated as blocks; its "pages" are units."""
    with tempfile.TemporaryDirectory() as tmp:
        all_units = blocks_mod.units(read_blocks(book, tmp))
    glossary = glossary_mod.load(glossary_path(state, target))
    if glossary_file:
        glossary.update(glossary_mod.parse_file(glossary_file))
    cache, used = load_cache(state.with_suffix(".cache.json")), load_cache(used_path(state))
    done = [u for u in parse_range(pages, len(all_units))
            if unit_cached(cache, unit_key(u, target), all_units[u])]
    stale = [u for u in done if is_stale(used, unit_key(u, target), glossary, blocks_mod.unit_text(all_units[u]))]
    return {"pages": [u + 1 for u in stale], "translated": len(done)}


def detect_book_language(book, sample=12):
    """The book's language code from pages spread over it, or None if it cannot be told
    (a scan has no text to read until it is OCR'd; the translating model then decides)."""
    book = Path(book)
    if book.suffix.lower() == ".pdf":
        import fitz
        with fitz.open(str(book)) as doc:
            n = len(doc)
            step = max(n / sample, 1)
            pages = [doc[int(k * step)].get_text() for k in range(min(sample, n))]
    else:
        pages = languages.sample_pages(book_pages(book), sample)
    return languages.detect_language(pages)


def build_source_pdf(book, idx, out):
    """A PDF of just the selected pages (for a page range), or None for the whole book."""
    from pypdf import PdfWriter
    r, w = open_pdf(book), PdfWriter()
    for i in idx:
        w.add_page(r.pages[i])
    path = out.with_suffix(".src.pdf")
    with open(path, "wb") as f:
        w.write(f)
    return path


def total_pages(book):
    """Pages in the book (quick for PDFs, which don't need their text read)."""
    book = Path(book)
    if book.suffix.lower() == ".pdf":
        return len(open_pdf(book).pages)
    return len(book_pages(book))


def count_pages(book, pages=None):
    """Number of pages a job would translate (for a cost estimate before it starts)."""
    return len(parse_range(pages, total_pages(book)))


def draft_glossary(book, translator, glossary_path, *, pages=None, progress=None, meter=None,
                   source="auto", target=languages.DEFAULT_TARGET):
    """Find the names of the chosen pages and fix a rendering for each; returns the glossary.

    The result is saved at `glossary_path`; translate_book picks it up when `glossary_path`
    is `<out>.glossary.json`, and only asks about names it does not hold yet. With a `meter`
    the calls are counted and stopped at its limit (the names found so far are kept).
    """
    book = Path(book)
    source, target = languages.check_source(source), languages.check_target(target)
    all_pages = book_pages(book)
    idx = parse_range(pages, len(all_pages))
    if source == "auto":
        source = languages.detect_language(languages.sample_pages(all_pages)) or "auto"
    if source != "auto" and source not in languages.NAME_CAPITALS:  # no capitalised names to find
        return glossary_mod.load(glossary_path)
    glossary = glossary_mod.load(glossary_path)
    if meter is not None:
        translator = Metered(translator, meter)
    try:
        glossary_mod.build(translator, all_pages, [all_pages[i] for i in idx], glossary, progress,
                           source, target)
    finally:
        glossary_mod.save(glossary_path, glossary)
    return glossary


def translate_book(book, out, translator, options=None, *, ocr_backend=None, progress=None,
                   meter=None, **settings):
    """Translate `book` (PDF, EPUB, Word, Markdown or text) into the file `out`; returns `out`.

    What to do is a `JobOptions` (options.py), or the same settings as keyword arguments:
    `translate_book(book, out, t, target="fr")` is `translate_book(book, out, t, JobOptions(target="fr"))`.
    Naming a setting that does not exist is a TypeError, a value that is not allowed a ValueError.
    The settings, with their defaults:

    translator    an LLMBackend that translates
    ocr_backend   a vision backend; scanned pages with no text layer are read with it
                  (without one, such pages stay blank)
    pages         page range such as "1-20"; redo: pages to re-translate despite the cache
    flat          PDF input: plain-text translated pages instead of the original layout
    source        language code of the book, or "auto" (default): detected from its text
                  (from the OCR text for scans); if that is unsure the model works it out
    target        language code to translate into (see languages.LANGUAGES), default zh-CN
    output_mode   "bilingual": each original page then its translation (default);
                  "target-only": only the translation
    output_format "pdf" (default), "epub", "docx" or "md". A PDF written as PDF keeps its page
                  layout and an EPUB written as EPUB its own file; every other pair carries the
                  text, pictures and tables over in their order. A Word or Markdown book, and an
                  EPUB or text book written as anything but PDF, is read as blocks (blocks.py)
    refresh_glossary  translate again the cached pages whose glossary entries have changed since
                  they were translated (after editing the glossary); the other pages and the
                  automatic glossary are left alone, so only those pages are paid for
    state         the file whose name the cache, OCR text and glossary files are built from
                  (default `out`); keep it the same across output modes to share the cache
    progress      progress(stage, done, total) with stage "scan", "ocr", "glossary",
                  "translate" or "render", called as pages complete
    glossary_file  text file of `original=translation` lines that override the glossary
    auto_glossary  find repeated names and fix one rendering for each, so a name
                  reads the same on every page (kept in `<out>.glossary.json`)

    meter         a spend.Meter: every model call is counted, and when the next call would
                  take the total over its limit SpendLimitReached is raised (the pages done so
                  far are already cached, so calling again with a higher limit carries on)
    only_cached   spend nothing: build the PDF from the pages already translated and leave out
                  the others (the way to finish after SpendLimitReached)

    Progress is cached next to `out`, so a repeated call resumes where it stopped.
    """
    if options is not None and settings:
        raise TypeError("Pass the settings as one JobOptions or as keyword arguments, not both.")
    o = options if options is not None else JobOptions(**settings)
    pages, redo, flat, glossary_file = o.pages, o.redo, o.flat, o.glossary_file
    only_cached, refresh_glossary, source, target, output_mode = (
        o.only_cached, o.refresh_glossary, o.source, o.target, o.output_mode)
    auto_glossary = o.auto_glossary and not refresh_glossary  # only the pages that changed are paid for
    book, out = Path(book), Path(out)
    state = o.state or out
    for folder in {out.parent, Path(state).parent}:  # -o some/new/folder/book.pdf; found out now, not after the first page is paid for
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise ValueError(f"Cannot write to the folder {folder}: {e.strerror or e}") from e
        if not os.access(folder, os.W_OK):
            raise ValueError(f"Cannot write to the folder {folder}: it is read-only.")
    overrides = glossary_mod.parse_file(glossary_file) if glossary_file else {}  # a bad file fails now, not after the OCR
    if book.suffix.lower() not in INPUTS:
        raise ValueError(f"Unsupported file type: {book.suffix.lower()} (use {', '.join(INPUTS)})")
    if reads_as_blocks(book, o.output_format):
        return _translate_blocks_book(book, out, translator, o, state, overrides, progress, meter)
    is_pdf = book.suffix.lower() == ".pdf"
    with failure.working_on(stage="read"):
        all_pages = read_book(book)
    idx = parse_range(pages, len(all_pages))
    if not idx:
        raise ValueError("The book has no pages." if not all_pages else
                         f"The page range {pages!r} is outside the book, which has {len(all_pages)} pages.")
    cache_path = state.with_suffix(".cache.json")
    if only_cached:
        cached = load_cache(cache_path)
        idx = [i for i in idx if cache_key(i, target) in cached or cache_key(i, target, True) in cached]
        if not idx:
            raise ValueError("Nothing has been translated yet.")
        translator, ocr_backend, auto_glossary, redo = NoCalls(), None, False, None
    elif meter is not None:
        translator = Metered(translator, meter)
        if ocr_backend is not None:
            ocr_backend = translator if ocr_backend is translator.inner else Metered(ocr_backend, meter)
    texts = [all_pages[i] for i in idx]

    scanned = ([n for n, t in enumerate(texts) if len(t.strip()) < MIN_TEXT_CHARS]
               if is_pdf else [])
    if scanned and only_cached:  # their text is in the OCR cache from the earlier run
        ocr_cache = load_cache(state.with_suffix(".ocr.json"))
        for n in scanned:
            texts[n] = ocr_cache.get(str(idx[n]), texts[n])
    elif scanned and ocr_backend:
        ocr_scanned_pages(ocr_backend, book, idx, texts, scanned,
                          state.with_suffix(".ocr.json"), progress)

    # text PDFs: translate block by block and redraw the original page in Chinese
    layout, ctx = ({}, {}) if not is_pdf or flat else \
        collect_layout(book, idx, skip=scanned, progress=progress)
    if only_cached:
        # A page translated by an earlier version may no longer match its blocks (the way a
        # page is cut into blocks has changed since). It cannot be redrawn without paying, so
        # it is left out like a page that was never translated.
        def usable(n):
            if n in layout:
                got = cached.get(cache_key(idx[n], target, True))
                if isinstance(got, list) and len(got) == len(layout[n]):
                    return True
                del layout[n]  # its plain-text translation, if there is one, still serves
                ctx.pop(n, None)
            return cache_key(idx[n], target) in cached
        keep = [n for n in range(len(idx)) if usable(n)]
        if not keep:
            raise ValueError("Nothing has been translated yet.")
        layout = {k: layout[n] for k, n in enumerate(keep) if n in layout}
        ctx = {k: ctx[n] for k, n in enumerate(keep) if n in ctx}
        idx, texts = [idx[n] for n in keep], [texts[n] for n in keep]

    book_texts = list(all_pages)  # the whole book, with the OCR text of the chosen pages
    for k, i in enumerate(idx):
        book_texts[i] = texts[k]
    if source == "auto":  # pages spread over the book, so a cover in another language is outvoted
        source = languages.detect_language(languages.sample_pages(book_texts)) or "auto"

    gloss_path = glossary_path(state, target)
    glossary = glossary_mod.load(gloss_path)
    if auto_glossary and (source == "auto" or source in languages.NAME_CAPITALS):
        try:
            glossary_mod.build(translator, book_texts, texts, glossary, progress, source, target)
        except SpendLimitReached:  # keep the names already paid for
            glossary_mod.save(gloss_path, glossary)
            raise
    glossary.update(overrides)
    if glossary:
        glossary_mod.save(gloss_path, glossary)

    cache = load_cache(cache_path)
    redo = set(parse_range(redo, len(all_pages))) if redo else set()
    translations = translate_all(translator, idx, texts, layout, ctx,
                                 cache, cache_path, redo, progress, glossary, source, target,
                                 used=load_cache(used_path(state)), used_path=used_path(state),
                                 refresh=refresh_glossary)

    if o.output_format != "pdf":  # a PDF written as another format: its text, pictures and tables in order
        found = pdf_blocks(book, idx, texts, layout, lambda n: cache[cache_key(idx[n], target, True)],
                           translations, assets_path(state))
        if progress:
            progress("render", 1, 1)
        with failure.working_on(stage="render"):
            write_blocks(found, assets_path(state), out, o.output_format,
                         bilingual=output_mode == "bilingual", lang=target, title=book.stem)
        return out

    original = None
    if is_pdf:  # keep the original page layout; a page range needs a trimmed copy
        original = build_source_pdf(book, idx, out) if pages or only_cached else book
    # measure every page first, so text of one style is one size through the book
    fits = {}
    for k, (n, blocks) in enumerate(layout.items(), 1):
        fits[n] = measure_layout_page(book, idx[n], blocks,
                                      cache[cache_key(idx[n], target, True)], target)
        if progress:
            progress("render", k, 2 * len(layout))
    ratios = book_ratios(fits.values())
    zh_pages = {}
    for k, (n, blocks) in enumerate(layout.items(), 1):
        zh_pages[n] = render_layout_page(book, idx[n], blocks,
                                         cache[cache_key(idx[n], target, True)], target,
                                         fits.pop(n), ratios)
        if progress:
            progress("render", len(layout) + k, 2 * len(layout))
    try:
        with failure.working_on(stage="render"):
            make_pdf(texts, translations, out, original, zh_pages,
                     source=source, target=target, mode=output_mode)
    finally:
        if original and original != book:
            original.unlink(missing_ok=True)
    return out


def _translate_blocks_book(book, out, translator, o, state, overrides, progress, meter):
    """translate_book for a book read as blocks (reads_as_blocks): the same settings, cache
    files and glossary; a "page" of the page range is a unit of about a page."""
    target, source = o.target, o.source
    assets = assets_path(state)
    with failure.working_on(stage="read"):
        found = read_blocks(book, assets)
    all_units = blocks_mod.units(found)
    idx = parse_range(o.pages, len(all_units))
    if not idx:
        raise ValueError("The book has no pages." if not all_units else
                         f"The page range {o.pages!r} is outside the book, which has {len(all_units)} pages.")
    cache_path = state.with_suffix(".cache.json")
    cache = load_cache(cache_path)
    auto_glossary = o.auto_glossary and not o.refresh_glossary
    redo = set(parse_range(o.redo, len(all_units))) if o.redo else set()
    if o.only_cached:
        idx = [u for u in idx if unit_cached(cache, unit_key(u, target), all_units[u])]
        if not idx:
            raise ValueError("Nothing has been translated yet.")
        translator, auto_glossary, redo = NoCalls(), False, set()
    elif meter is not None:
        translator = Metered(translator, meter)
    book_texts = [blocks_mod.unit_text(u) for u in all_units]
    texts = [book_texts[u] for u in idx]
    if source == "auto":
        source = languages.detect_language(languages.sample_pages(book_texts)) or "auto"

    gloss_path = glossary_path(state, target)
    glossary = glossary_mod.load(gloss_path)
    if auto_glossary and (source == "auto" or source in languages.NAME_CAPITALS):
        try:
            glossary_mod.build(translator, book_texts, texts, glossary, progress, source, target)
        except SpendLimitReached:  # keep the names already paid for
            glossary_mod.save(gloss_path, glossary)
            raise
    glossary.update(overrides)
    if glossary:
        glossary_mod.save(gloss_path, glossary)

    translate_units(translator, found, all_units, idx, cache, cache_path, redo, progress, glossary,
                    source, target, used=load_cache(used_path(state)), used_path=used_path(state),
                    refresh=o.refresh_glossary, marks=book.suffix.lower() in MARKDOWN)

    whole = len(idx) == len(all_units)
    if not whole:  # a unit's blocks run up to the next unit's first block
        starts = [u[0][0] for u in all_units] + [len(found)]
        keep = sorted({k for u in idx for k in range(0 if u == 0 else starts[u], max(starts[u + 1], starts[u] + 1))}
                      | {k for u in idx for k, _, _ in all_units[u]})
        found = [found[k] for k in keep]
    if progress:
        progress("render", 1, 1)
    with failure.working_on(stage="render"):
        write_blocks(found, assets, out, o.output_format, bilingual=o.output_mode == "bilingual",
                     lang=target, title=book.stem, source=book if whole else None)
    return out
