"""Command-line entry point: wires readers, OCR, translation and the writer."""
import argparse
import sys
from pathlib import Path

from .backends import BACKENDS, make_backend
from .layout import collect_layout, render_layout_page
from .ocr import ocr_scanned_pages
from .readers import parse_range, read_book
from .translate import load_cache, translate_all
from .usage import Usage
from .writer import make_pdf

MIN_TEXT_CHARS = 20  # PDF pages with less text than this are treated as scans

DOC = """Translate an English book (PDF / EPUB / TXT) into a bilingual PDF.

Every English page is followed by a page with its Chinese translation.

Usage:
    python -m booktrans book.epub -o book_bilingual.pdf
    python -m booktrans book.pdf --pages 1-20      # try a few pages first
    python -m booktrans scan.pdf --ocr             # scanned PDF (no text layer)
"""


def parse_args():
    ap = argparse.ArgumentParser(description=DOC,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("book", type=Path)
    ap.add_argument("-o", "--output", type=Path)
    ap.add_argument("--backend", choices=list(BACKENDS), default="claude-cli",
                    help="claude-cli uses your Claude Code login (default); "
                         "api needs ANTHROPIC_API_KEY")
    ap.add_argument("--model", help="model name (default: backend's default)")
    ap.add_argument("--pages", help="page range to translate, e.g. 1-20")
    ap.add_argument("--redo", help="re-translate these pages even if cached, e.g. 9-10")
    ap.add_argument("--flat", action="store_true",
                    help="PDF input: typeset the translation as plain text pages "
                         "instead of copying each page's layout")
    ap.add_argument("--ocr", action="store_true",
                    help="OCR scanned PDF pages (no text layer) with a vision model")
    ap.add_argument("--ocr-backend", choices=list(BACKENDS),
                    help="backend for OCR (default: --backend)")
    ap.add_argument("--ocr-model", help="model for OCR (default: --model)")
    return ap.parse_args()


def build_source_pdf(book, idx, out):
    """A PDF of just the selected pages (for --pages), or None for the whole book."""
    from pypdf import PdfReader, PdfWriter
    r, w = PdfReader(str(book)), PdfWriter()
    for i in idx:
        w.add_page(r.pages[i])
    path = out.with_suffix(".src.pdf")
    with open(path, "wb") as f:
        w.write(f)
    return path


def main():
    args = parse_args()
    usage = Usage()
    is_pdf = args.book.suffix.lower() == ".pdf"

    translator = make_backend(args.backend, args.model, usage)
    ocr_backend = translator
    if args.ocr:
        if args.ocr_backend or args.ocr_model:
            ocr_backend = make_backend(args.ocr_backend or args.backend,
                                       args.ocr_model or args.model, usage)
        if not ocr_backend.supports_vision:
            sys.exit(f"--ocr needs a vision-capable backend; "
                     f"{type(ocr_backend).__name__} has none. Try --ocr-backend.")

    all_pages = read_book(args.book)
    idx = parse_range(args.pages, len(all_pages))
    pages = [all_pages[i] for i in idx]
    suffix = " pages " + args.pages.replace(" ", "") if args.pages else ""
    out = args.output or args.book.with_name(f"{args.book.stem}_bilingual{suffix}.pdf")
    cache_path = out.with_suffix(".cache.json")

    scanned = ([n for n, t in enumerate(pages) if len(t.strip()) < MIN_TEXT_CHARS]
               if is_pdf else [])
    if scanned and not args.ocr:
        print(f"Warning: {len(scanned)} of {len(pages)} pages have no text layer "
              "(scanned?). Re-run with --ocr to read them.", file=sys.stderr)
    elif scanned:
        ocr_scanned_pages(ocr_backend, args.book, idx, pages, scanned,
                          out.with_suffix(".ocr.json"))

    # text PDFs: translate block by block and redraw the original page in Chinese
    layout, ctx = ({}, {}) if not is_pdf or args.flat else \
        collect_layout(args.book, idx, skip=scanned)

    redo = set(parse_range(args.redo, len(all_pages))) if args.redo else set()
    cache = load_cache(cache_path)
    translations = translate_all(translator, idx, pages, layout, ctx,
                                 cache, cache_path, redo)

    original = None
    if is_pdf:
        # keep the original page layout; a page range needs a trimmed copy
        original = build_source_pdf(args.book, idx, out) if args.pages else args.book
    zh_pages = {n: render_layout_page(args.book, idx[n], blocks, cache["L%d" % idx[n]])
                for n, blocks in layout.items()}
    make_pdf(pages, translations, out, original, zh_pages)
    if original and original != args.book:
        original.unlink()
    print(f"Done: {out}")
    usage.report(out)
