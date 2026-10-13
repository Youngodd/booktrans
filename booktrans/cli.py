"""Command-line entry point: wires readers, OCR, translation and the writer."""
import argparse
import sys
from pathlib import Path

from .backends import BACKENDS, make_backend
from .backends.base import BackendError
from .pipeline import MIN_TEXT_CHARS, default_output, translate_book
from .readers import parse_range, read_book
from .usage import Usage

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
                         "api needs ANTHROPIC_API_KEY; qwen, qwen-intl, deepseek, "
                         "openai-compatible need DASHSCOPE_API_KEY / DEEPSEEK_API_KEY / "
                         "BOOKTRANS_API_KEY")
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


def make_progress():
    """Print one line per page for the slow stages (translation, OCR)."""
    def progress(stage, done, total):
        if stage in ("translate", "ocr"):
            print(f"{'OCR' if stage == 'ocr' else 'Translating'} page {done}/{total}...",
                  flush=True)
    return progress


def main():
    args = parse_args()
    try:
        run(args)
    except (ValueError, BackendError) as e:
        sys.exit(f"{e}\nProgress is saved; run the same command again to resume."
                 if isinstance(e, BackendError) else str(e))


def run(args):
    usage = Usage()
    is_pdf = args.book.suffix.lower() == ".pdf"

    translator = make_backend(args.backend, args.model, usage)
    ocr_backend = None
    if args.ocr:
        ocr_backend = translator
        if args.ocr_backend or args.ocr_model:
            ocr_backend = make_backend(args.ocr_backend or args.backend,
                                       args.ocr_model or args.model, usage,
                                       vision_model=args.ocr_model)
        if not ocr_backend.supports_vision:
            sys.exit(f"--ocr needs a vision-capable backend; "
                     f"{type(ocr_backend).__name__} has none. Try --ocr-backend.")

    pages = read_book(args.book)
    idx = parse_range(args.pages, len(pages))
    scanned = [i for i in idx if len(pages[i].strip()) < MIN_TEXT_CHARS] if is_pdf else []
    if scanned and not args.ocr:
        print(f"Warning: {len(scanned)} of {len(idx)} pages have no text layer "
              "(scanned?). Re-run with --ocr to read them.", file=sys.stderr)

    out = args.output or default_output(args.book, args.pages)
    translate_book(args.book, out, translator, ocr_backend=ocr_backend, pages=args.pages,
                   redo=args.redo, flat=args.flat, progress=make_progress())
    print(f"Done: {out}")
    usage.report(out)
