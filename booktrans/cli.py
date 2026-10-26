"""Command-line entry point: wires readers, OCR, translation and the writer."""
import argparse
import sys
from pathlib import Path

from .backends import BACKENDS, make_backend
from .backends.base import BackendError
from .pipeline import MIN_TEXT_CHARS, default_output, translate_book
from .readers import parse_range, read_book
from .spend import DEFAULT_LIMIT_CNY, Meter, SpendLimitReached, rest_estimate
from .usage import Usage

EXIT_SPEND_LIMIT = 3  # stopped at the spend limit; progress is saved

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
    ap.add_argument("--glossary", type=Path,
                    help="text file of `English=中文` lines: fixed renderings of names and "
                         "terms (they override the automatic glossary)")
    ap.add_argument("--no-auto-glossary", action="store_true",
                    help="do not build the automatic glossary of repeated names")
    ap.add_argument("--ocr", action="store_true",
                    help="OCR scanned PDF pages (no text layer) with a vision model")
    ap.add_argument("--ocr-backend", choices=list(BACKENDS),
                    help="backend for OCR (default: --backend)")
    ap.add_argument("--ocr-model", help="model for OCR (default: --model)")
    ap.add_argument("--max-spend", type=float, default=DEFAULT_LIMIT_CNY, metavar="YUAN",
                    help="stop and ask before spending more than this many yuan on the book "
                         "in total, across runs (default %(default)s; 0 = no limit). Prices "
                         "are estimates; see booktrans/spend.py")
    ap.add_argument("--finish-partial", action="store_true",
                    help="spend nothing: write the PDF from the pages already translated")
    return ap.parse_args()


def make_progress():
    """Print one line per page for the slow stages (translation, OCR)."""
    def progress(stage, done, total):
        if stage == "glossary":
            print(f"Glossary: {done}/{total} names...", flush=True)
        elif stage in ("translate", "ocr"):
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


def decide(e, last, out):
    """The spend limit was reached: ask what to do. Returns ("raise", yuan), ("finish",) or ("cancel",)."""
    rest = rest_estimate(e.spent, last.get("done", 0), last.get("total", 0)) if last.get("stage") == "translate" else None
    print(f"\nSpend limit reached: ¥{e.spent:.2f} of ¥{e.limit:.2f}. The pages translated so far are saved."
          + (f" About ¥{rest:.2f} more is needed to finish (a rough estimate)." if rest else ""))
    if not sys.stdin.isatty():
        print(f"Run again with --max-spend N (more than {e.spent:.2f}, or 0 for no limit) to carry on, "
              f"or with --finish-partial to write the PDF from the pages already translated.",
              file=sys.stderr)
        sys.exit(EXIT_SPEND_LIMIT)
    while True:
        answer = input("[r] raise the limit and continue   [f] finish with the translated pages   "
                       "[c] cancel > ").strip().lower()
        if answer == "r":
            try:
                new = float(input(f"New limit in yuan, more than {e.spent:.2f} (0 = no limit): "))
            except ValueError:
                continue
            if new == 0 or new > e.spent:
                return ("raise", new)
        elif answer == "f":
            return ("finish",)
        elif answer == "c":
            return ("cancel",)


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
    if args.finish_partial:
        translate_book(args.book, out, translator, pages=args.pages, flat=args.flat, only_cached=True)
        print(f"Done (translated pages only): {out}")
        return
    limit, last, show = args.max_spend, {}, make_progress()

    def progress(stage, done, total):
        last.update(stage=stage, done=done, total=total)
        show(stage, done, total)

    try:
        while True:
            meter = Meter(limit, out.with_suffix(".spend.json"))  # the total is kept across runs
            try:
                translate_book(args.book, out, translator, ocr_backend=ocr_backend, pages=args.pages,
                               redo=args.redo, flat=args.flat, progress=progress,
                               glossary_file=args.glossary, auto_glossary=not args.no_auto_glossary,
                               meter=meter)
                break
            except SpendLimitReached as e:
                choice = decide(e, last, out)
                if choice[0] == "raise":
                    limit = choice[1]
                elif choice[0] == "finish":
                    translate_book(args.book, out, translator, pages=args.pages, flat=args.flat,
                                   only_cached=True)
                    print(f"Done (translated pages only): {out}")
                    return
                else:
                    sys.exit("Cancelled. Progress is saved; run the same command to carry on.")
        print(f"Done: {out}")
    finally:
        usage.report(out)  # once, for everything this run paid for
