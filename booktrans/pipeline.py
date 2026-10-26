"""The whole job as a function: read a book, translate it, write the bilingual PDF.

Used by the command line (cli.py) and callable from other programs, such as a web
service. Nothing here prints or exits; progress goes to an optional callback.
"""
from pathlib import Path

from . import glossary as glossary_mod
from .layout import collect_layout, render_layout_page
from .ocr import ocr_scanned_pages
from .readers import parse_range, read_book
from .spend import Metered, NoCalls, SpendLimitReached
from .translate import load_cache, translate_all
from .writer import make_pdf

class Cancelled(Exception):
    """Raised by a `progress` callback to stop translate_book; the cache keeps finished pages."""


MIN_TEXT_CHARS = 20  # PDF pages with less text than this are treated as scans


def default_output(book, pages=None):
    """Where the bilingual PDF goes when no output path is given."""
    book = Path(book)
    suffix = " pages " + pages.replace(" ", "") if pages else ""
    return book.with_name(f"{book.stem}_bilingual{suffix}.pdf")


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


def draft_glossary(book, translator, glossary_path, *, pages=None, progress=None, meter=None):
    """Find the names of the chosen pages and fix a rendering for each; returns the glossary.

    The result is saved at `glossary_path`; translate_book picks it up when `glossary_path`
    is `<out>.glossary.json`, and only asks about names it does not hold yet. With a `meter`
    the calls are counted and stopped at its limit (the names found so far are kept).
    """
    book = Path(book)
    all_pages = read_book(book)
    idx = parse_range(pages, len(all_pages))
    glossary = glossary_mod.load(glossary_path)
    if meter is not None:
        translator = Metered(translator, meter)
    try:
        glossary_mod.build(translator, all_pages, [all_pages[i] for i in idx], glossary, progress)
    finally:
        glossary_mod.save(glossary_path, glossary)
    return glossary


def translate_book(book, out, translator, *, ocr_backend=None, pages=None, redo=None,
                   flat=False, progress=None, glossary_file=None, auto_glossary=True,
                   meter=None, only_cached=False):
    """Translate `book` into the bilingual PDF `out`; returns `out`.

    translator    an LLMBackend that translates
    ocr_backend   a vision backend; scanned pages with no text layer are read with it
                  (without one, such pages stay blank)
    pages         page range such as "1-20"; redo: pages to re-translate despite the cache
    flat          PDF input: plain-text Chinese pages instead of the original layout
    progress      progress(stage, done, total) with stage "scan", "ocr", "glossary",
                  "translate" or "render", called as pages complete
    glossary_file  text file of `English=中文` lines that override the glossary
    auto_glossary  find repeated names and fix one Chinese rendering for each, so a name
                  reads the same on every page (kept in `<out>.glossary.json`)

    meter         a spend.Meter: every model call is counted, and when the next call would
                  take the total over its limit SpendLimitReached is raised (the pages done so
                  far are already cached, so calling again with a higher limit carries on)
    only_cached   spend nothing: build the PDF from the pages already translated and leave out
                  the others (the way to finish after SpendLimitReached)

    Progress is cached next to `out`, so a repeated call resumes where it stopped.
    """
    book, out = Path(book), Path(out)
    is_pdf = book.suffix.lower() == ".pdf"
    all_pages = read_book(book)
    idx = parse_range(pages, len(all_pages))
    cache_path = out.with_suffix(".cache.json")
    if only_cached:
        cached = load_cache(cache_path)
        idx = [i for i in idx if str(i) in cached or "L%d" % i in cached]
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
        ocr_cache = load_cache(out.with_suffix(".ocr.json"))
        for n in scanned:
            texts[n] = ocr_cache.get(str(idx[n]), texts[n])
    elif scanned and ocr_backend:
        ocr_scanned_pages(ocr_backend, book, idx, texts, scanned,
                          out.with_suffix(".ocr.json"), progress)

    # text PDFs: translate block by block and redraw the original page in Chinese
    layout, ctx = ({}, {}) if not is_pdf or flat else \
        collect_layout(book, idx, skip=scanned, progress=progress)

    glossary_path = out.with_suffix(".glossary.json")
    glossary = glossary_mod.load(glossary_path)
    if auto_glossary:
        book_texts = list(all_pages)  # the whole book, with the OCR text of the chosen pages
        for k, i in enumerate(idx):
            book_texts[i] = texts[k]
        try:
            glossary_mod.build(translator, book_texts, texts, glossary, progress)
        except SpendLimitReached:  # keep the names already paid for
            glossary_mod.save(glossary_path, glossary)
            raise
    if glossary_file:
        glossary.update(glossary_mod.parse_file(glossary_file))
    if glossary:
        glossary_mod.save(glossary_path, glossary)

    cache = load_cache(cache_path)
    redo = set(parse_range(redo, len(all_pages))) if redo else set()
    translations = translate_all(translator, idx, texts, layout, ctx,
                                 cache, cache_path, redo, progress, glossary)

    original = None
    if is_pdf:  # keep the original page layout; a page range needs a trimmed copy
        original = build_source_pdf(book, idx, out) if pages or only_cached else book
    zh_pages = {}
    for k, (n, blocks) in enumerate(layout.items(), 1):
        zh_pages[n] = render_layout_page(book, idx[n], blocks, cache["L%d" % idx[n]])
        if progress:
            progress("render", k, len(layout))
    try:
        make_pdf(texts, translations, out, original, zh_pages)
    finally:
        if original and original != book:
            original.unlink(missing_ok=True)
    return out
