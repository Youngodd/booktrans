"""Command-line entry point: wires readers, OCR, translation and the writer."""
import argparse
import math
import sys
from pathlib import Path

from .backends import BACKENDS, make_backend
from .backends.base import BackendError
from . import languages
from . import glossary as glossary_mod
from .pipeline import MIN_TEXT_CHARS, default_output, draft_glossary, glossary_changes, glossary_path, translate_book
from .readers import parse_range, read_book
from .spend import DEFAULT_LIMIT_CNY, Meter, SpendLimitReached, est_cny_per_page, rest_estimate
from .usage import Usage

EXIT_SPEND_LIMIT = 3  # stopped at the spend limit; progress is saved

DOC = """Translate a book (PDF / EPUB / TXT) from one language into another with AI.

The source language is detected from the book (override it with --source). By default
every original page is followed by a page with its translation (a bilingual PDF);
--output-mode target-only writes the translation alone.

Usage:
    python -m booktrans book.epub -o book_bilingual.pdf
    python -m booktrans livre.pdf --target en      # French (detected) -> English
    python -m booktrans book.pdf --target ja --output-mode target-only
    python -m booktrans book.pdf --pages 1-20      # try a few pages first
    python -m booktrans scan.pdf --ocr             # scanned PDF (no text layer)

Check the names early, fix them, and apply the fixes to pages already translated:
    python -m booktrans book.pdf --export-glossary names.txt    # collect names, write the file, stop
    (edit names.txt: one `original=translation` per line)
    python -m booktrans book.pdf --glossary names.txt --apply-glossary

Languages (--source / --target): %s
""" % ", ".join(f"{c} ({v[0]})" for c, v in languages.LANGUAGES.items())


def _limit(value):
    """argparse type of --max-spend: 0 (no limit) or a positive, finite number."""
    try:
        n = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not a number")
    if not math.isfinite(n) or n < 0:
        raise argparse.ArgumentTypeError("must be 0 (no limit) or a positive number")
    return n


def parse_args():
    ap = argparse.ArgumentParser(description=DOC,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("book", type=Path)
    ap.add_argument("-o", "--output", type=Path)
    ap.add_argument("--source", default="auto", metavar="LANG",
                    help="language of the book, e.g. fr; default auto = detect it")
    ap.add_argument("--target", default=languages.DEFAULT_TARGET, metavar="LANG",
                    help="language to translate into (default %(default)s)")
    ap.add_argument("--output-mode", choices=languages.OUTPUT_MODES, default="bilingual",
                    help="bilingual: each original page then its translation (default); "
                         "target-only: only the translated pages")
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
                    help="text file of `original=translation` lines: fixed renderings of names and "
                         "terms (they override the automatic glossary)")
    ap.add_argument("--export-glossary", type=Path, metavar="FILE",
                    help="collect the book's names, write them to FILE as `original=translation` lines "
                         "for you to check and edit, and stop (only the names are paid for)")
    ap.add_argument("--apply-glossary", action="store_true",
                    help="after editing the glossary (--glossary FILE), translate again only the pages "
                         "already translated whose names changed; the others keep their translation")
    ap.add_argument("--no-auto-glossary", action="store_true",
                    help="do not build the automatic glossary of repeated names")
    ap.add_argument("--ocr", action="store_true",
                    help="OCR scanned PDF pages (no text layer) with a vision model")
    ap.add_argument("--ocr-backend", choices=list(BACKENDS),
                    help="backend for OCR (default: --backend)")
    ap.add_argument("--ocr-model", help="model for OCR (default: --model)")
    ap.add_argument("--max-spend", type=_limit, default=DEFAULT_LIMIT_CNY, metavar="YUAN",
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
        args.source = languages.check_source(args.source)
        args.target = languages.check_target(args.target)
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


def export_glossary(args, translator, state):
    """Collect the names of the book, write them to --export-glossary, and stop."""
    meter = Meter(args.max_spend, state.with_suffix(".spend.json"))
    try:
        found = draft_glossary(args.book, translator, glossary_path(state, args.target), pages=args.pages,
                               meter=meter, source=args.source, target=args.target)
    except SpendLimitReached as e:
        print(f"Spend limit reached while collecting names: ¥{e.spent:.2f} of ¥{e.limit:.2f}.", file=sys.stderr)
        sys.exit(EXIT_SPEND_LIMIT)
    if args.glossary:
        found.update(glossary_mod.parse_file(args.glossary))
    text = glossary_mod.dumps(found)
    if text == glossary_mod.HEADER:
        print("No names to fix were found in this book.")
        return
    args.export_glossary.write_text(text, encoding="utf-8")
    print(f"Wrote {sum(1 for zh in found.values() if zh)} names to {args.export_glossary}.\n"
          "Edit it, then: python -m booktrans <book> --glossary FILE --apply-glossary")


def confirm_apply(args, out, state):
    """Say which pages the edited glossary changes and what translating them again costs.
    Returns False when there is nothing to do or the user declines."""
    found = glossary_changes(args.book, out, pages=args.pages, flat=args.flat, target=args.target,
                             glossary_file=args.glossary, state=state)
    n = len(found["pages"])
    if not found["translated"]:
        print("Nothing has been translated yet, so there is nothing to apply the glossary to.")
        return False
    if not n:
        print(f"None of the {found['translated']} translated pages is affected by the glossary changes.")
        return False
    rate = est_cny_per_page().get(args.backend)
    cost = f", about ¥{n * rate:.2f} (a rough estimate)" if rate else ""
    shown = ", ".join(map(str, found["pages"][:15])) + (" ..." if n > 15 else "")
    print(f"{n} of {found['translated']} translated pages mention a changed name and will be translated "
          f"again{cost}: pages {shown}")
    if sys.stdin.isatty():
        return input("Translate them again? [y/N] ").strip().lower() in ("y", "yes")
    return True


def run(args):
    if args.apply_glossary and args.finish_partial:
        sys.exit("--apply-glossary translates pages again; it cannot be combined with --finish-partial.")
    if not args.book.is_file():
        sys.exit(f"No such file: {args.book}")
    if args.glossary and not args.glossary.is_file():
        sys.exit(f"No such glossary file: {args.glossary}")
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

    out = args.output or default_output(args.book, args.pages, args.output_mode, args.target)
    # cache, OCR text and glossary sit next to the bilingual name whatever the mode, so
    # changing only --output-mode re-uses every page already translated
    state = args.output or default_output(args.book, args.pages)
    lang = dict(source=args.source, target=args.target, output_mode=args.output_mode, state=state)
    if args.export_glossary:
        export_glossary(args, translator, state)
        return
    if args.apply_glossary:
        if not confirm_apply(args, out, state):
            return
        lang["refresh_glossary"] = True
    if args.finish_partial:
        translate_book(args.book, out, translator, pages=args.pages, flat=args.flat, only_cached=True,
                       **lang)
        print(f"Done (translated pages only): {out}")
        return
    limit, last, show = args.max_spend, {}, make_progress()

    def progress(stage, done, total):
        last.update(stage=stage, done=done, total=total)
        show(stage, done, total)

    try:
        while True:
            meter = Meter(limit, state.with_suffix(".spend.json"))  # the total is kept across runs
            try:
                translate_book(args.book, out, translator, ocr_backend=ocr_backend, pages=args.pages,
                               redo=args.redo, flat=args.flat, progress=progress,
                               glossary_file=args.glossary, auto_glossary=not args.no_auto_glossary,
                               meter=meter, **lang)
                break
            except SpendLimitReached as e:
                choice = decide(e, last, out)
                if choice[0] == "raise":
                    limit = choice[1]
                elif choice[0] == "finish":
                    translate_book(args.book, out, translator, pages=args.pages, flat=args.flat,
                                   only_cached=True, **{k: v for k, v in lang.items() if k != "refresh_glossary"})
                    print(f"Done (translated pages only): {out}")
                    return
                else:
                    sys.exit("Cancelled. Progress is saved; run the same command to carry on.")
        print(f"Done: {out}")
    finally:
        usage.report(out)  # once, for everything this run paid for
