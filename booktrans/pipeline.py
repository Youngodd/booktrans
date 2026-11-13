"""The whole job as a function: read a book, translate it, write the translated PDF.

Used by the command line (cli.py) and callable from other programs, such as a web
service. Nothing here prints or exits; progress goes to an optional callback.
"""
from pathlib import Path

from . import glossary as glossary_mod
from . import languages
from .layout import collect_layout, render_layout_page
from .ocr import ocr_scanned_pages
from .options import JobOptions
from .readers import parse_range, read_book
from .spend import Metered, NoCalls, SpendLimitReached
from .translate import cache_key, load_cache, stale_positions, translate_all
from .writer import make_pdf

class Cancelled(Exception):
    """Raised by a `progress` callback to stop translate_book; the cache keeps finished pages."""


MIN_TEXT_CHARS = 20  # PDF pages with less text than this are treated as scans


def default_output(book, pages=None, mode="bilingual", target=languages.DEFAULT_TARGET):
    """Where the PDF goes when no output path is given: `<book>_bilingual.pdf`, or
    `<book>_<target>.pdf` for a translation-only PDF."""
    book = Path(book)
    suffix = " pages " + pages.replace(" ", "") if pages else ""
    tag = "bilingual" if mode == "bilingual" else target
    return book.with_name(f"{book.stem}_{tag}{suffix}.pdf")


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
        pages = languages.sample_pages(read_book(book), sample)
    return languages.detect_language(pages)


def build_source_pdf(book, idx, out):
    """A PDF of just the selected pages (for a page range), or None for the whole book."""
    from pypdf import PdfReader, PdfWriter
    r, w = PdfReader(str(book)), PdfWriter()
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
        from pypdf import PdfReader
        return len(PdfReader(str(book)).pages)
    return len(read_book(book))


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
    all_pages = read_book(book)
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
    """Translate `book` into the PDF `out`; returns `out`.

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
    overrides = glossary_mod.parse_file(glossary_file) if glossary_file else {}  # a bad file fails now, not after the OCR
    is_pdf = book.suffix.lower() == ".pdf"
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

    original = None
    if is_pdf:  # keep the original page layout; a page range needs a trimmed copy
        original = build_source_pdf(book, idx, out) if pages or only_cached else book
    zh_pages = {}
    for k, (n, blocks) in enumerate(layout.items(), 1):
        zh_pages[n] = render_layout_page(book, idx[n], blocks,
                                         cache[cache_key(idx[n], target, True)], target)
        if progress:
            progress("render", k, len(layout))
    try:
        make_pdf(texts, translations, out, original, zh_pages,
                 source=source, target=target, mode=output_mode)
    finally:
        if original and original != book:
            original.unlink(missing_ok=True)
    return out
