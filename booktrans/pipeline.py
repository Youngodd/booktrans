"""The whole job as a function: read a book, translate it, write the bilingual PDF.

Used by the command line (cli.py) and callable from other programs, such as a web
service. Nothing here prints or exits; progress goes to an optional callback.
"""
from pathlib import Path

from .layout import collect_layout, render_layout_page
from .ocr import ocr_scanned_pages
from .readers import parse_range, read_book
from .translate import load_cache, translate_all
from .writer import make_pdf

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


def translate_book(book, out, translator, *, ocr_backend=None, pages=None, redo=None,
                   flat=False, progress=None):
    """Translate `book` into the bilingual PDF `out`; returns `out`.

    translator    an LLMBackend that translates
    ocr_backend   a vision backend; scanned pages with no text layer are read with it
                  (without one, such pages stay blank)
    pages         page range such as "1-20"; redo: pages to re-translate despite the cache
    flat          PDF input: plain-text Chinese pages instead of the original layout
    progress      progress(stage, done, total) with stage "scan", "ocr", "translate" or
                  "render", called as pages complete

    Progress is cached next to `out`, so a repeated call resumes where it stopped.
    """
    book, out = Path(book), Path(out)
    is_pdf = book.suffix.lower() == ".pdf"
    all_pages = read_book(book)
    idx = parse_range(pages, len(all_pages))
    texts = [all_pages[i] for i in idx]
    cache_path = out.with_suffix(".cache.json")

    scanned = ([n for n, t in enumerate(texts) if len(t.strip()) < MIN_TEXT_CHARS]
               if is_pdf else [])
    if scanned and ocr_backend:
        ocr_scanned_pages(ocr_backend, book, idx, texts, scanned,
                          out.with_suffix(".ocr.json"), progress)

    # text PDFs: translate block by block and redraw the original page in Chinese
    layout, ctx = ({}, {}) if not is_pdf or flat else \
        collect_layout(book, idx, skip=scanned, progress=progress)

    cache = load_cache(cache_path)
    redo = set(parse_range(redo, len(all_pages))) if redo else set()
    translations = translate_all(translator, idx, texts, layout, ctx,
                                 cache, cache_path, redo, progress)

    original = None
    if is_pdf:  # keep the original page layout; a page range needs a trimmed copy
        original = build_source_pdf(book, idx, out) if pages else book
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
