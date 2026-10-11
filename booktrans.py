#!/usr/bin/env python3
"""Translate an English book (PDF / EPUB / TXT) into a bilingual PDF.

Every English page is followed by a page with its Chinese translation.

Usage:
    export ANTHROPIC_API_KEY=...
    python booktrans.py book.epub -o book_bilingual.pdf
    python booktrans.py book.pdf --pages 1-20      # try a few pages first
    python booktrans.py scan.pdf --ocr             # scanned PDF (no text layer)
"""
import argparse
import base64
import io
import json
import re
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape

MIN_TEXT_CHARS = 20    # PDF pages with less text than this are treated as scans
OCR_DPI = 150
CHARS_PER_PAGE = 1800  # for EPUB/TXT, which have no fixed pages
DEFAULT_MODEL = "claude-sonnet-5-5"

SYSTEM_PROMPT = (
    "You are a professional book translator. Translate the user's English text "
    "into natural, fluent Simplified Chinese. Preserve paragraph breaks. Keep "
    "proper names consistent; on first use you may add the English in parentheses. "
    "Keep the line structure: a single line break in the input (list items, "
    "table-of-contents entries, headings) must stay a separate line in the output. "
    "Output only the translation, with no commentary."
)

OCR_PROMPT = (
    "Transcribe all the text on this scanned book page exactly as printed. "
    "Join lines of the same paragraph into one line and separate paragraphs with "
    "a blank line; keep headings, list items and table-of-contents entries on "
    "their own lines. Omit page numbers and running headers/footers. Do not "
    "translate, correct or add anything. If the page has no text, output nothing. "
    "Output only the transcribed text."
)


# ---------- reading ----------

def reflow(text):
    """Rebuild paragraphs from layout-mode text.

    Blank lines separate blocks. Prose blocks (long lines) are joined into one
    paragraph; list/TOC-like blocks (short lines) keep one item per line.
    """
    paras, block = [], []

    def flush():
        if not block:
            return
        avg = sum(len(l) for l in block) / len(block)
        paras.append(" ".join(block) if avg > 50 else "\n".join(block))
        block.clear()

    for line in text.splitlines():
        line = re.sub(r"\s{2,}", " ", line.strip())
        if line:
            block.append(line)
        else:
            flush()
    flush()
    return "\n\n".join(paras)


def read_pdf(path):
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    return [reflow(p.extract_text(extraction_mode="layout") or "") for p in reader.pages]


def read_epub(path):
    import ebooklib
    from ebooklib import epub
    from bs4 import BeautifulSoup
    book = epub.read_epub(str(path))
    paras = []
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        soup = BeautifulSoup(item.get_content(), "html.parser")
        for el in soup.find_all(["h1", "h2", "h3", "p"]):
            text = el.get_text(" ", strip=True)
            if text:
                paras.append(text)
    return paginate(paras)


def read_txt(path):
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return paginate([p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()])


def paginate(paras):
    pages, cur, size = [], [], 0
    for p in paras:
        if cur and size + len(p) > CHARS_PER_PAGE:
            pages.append("\n\n".join(cur))
            cur, size = [], 0
        cur.append(p)
        size += len(p)
    if cur:
        pages.append("\n\n".join(cur))
    return pages


def read_book(path):
    ext = Path(path).suffix.lower()
    readers = {".pdf": read_pdf, ".epub": read_epub, ".txt": read_txt}
    if ext not in readers:
        sys.exit(f"Unsupported file type: {ext} (use .pdf, .epub or .txt)")
    return readers[ext](path)


# ---------- token usage ----------

USAGE = {"calls": 0, "input_tokens": 0, "output_tokens": 0,
         "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
         "cost_usd": 0.0}  # cost_usd is only reported by the claude-cli backend


def record_usage(usage, cost=None):
    """Add one call's usage (API object or CLI dict) to the running totals."""
    get = usage.get if isinstance(usage, dict) else lambda k: getattr(usage, k, 0)
    USAGE["calls"] += 1
    for k in ("input_tokens", "output_tokens",
              "cache_creation_input_tokens", "cache_read_input_tokens"):
        USAGE[k] += get(k) or 0
    USAGE["cost_usd"] += cost or 0.0


def run_cli(cmd, **kw):
    """Run `claude -p` with JSON output; record usage and return the text result."""
    r = subprocess.run(cmd + ["--output-format", "json"],
                                     capture_output=True, text=True, **kw)
    try:
        data = json.loads(r.stdout)
    except ValueError:
        data = None
    if r.returncode != 0 or not data or data.get("is_error"):
        sys.exit(f"claude CLI failed: {r.stderr.strip() or r.stdout.strip()}")
    record_usage(data.get("usage") or {}, data.get("total_cost_usd"))
    return data.get("result", "").strip()


# ---------- OCR (scanned PDFs) ----------

def ocr_page(client, model, path, i):
    """Transcribe page i of a scanned PDF with Claude's vision."""
    import fitz  # pymupdf
    with fitz.open(str(path)) as doc:
        img = doc[i].get_pixmap(dpi=OCR_DPI).tobytes("jpeg")
    if client is None:  # claude CLI: let its Read tool open the page image
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "page.jpg").write_bytes(img)
            cmd = ["claude", "-p", "Read the image file page.jpg. " + OCR_PROMPT,
                   "--tools", "Read", "--allowedTools", "Read",
                   "--no-session-persistence"]
            if model:
                cmd += ["--model", model]
            return run_cli(cmd, cwd=tmp, stdin=subprocess.DEVNULL)
    msg = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {
                "type": "base64", "media_type": "image/jpeg",
                "data": base64.b64encode(img).decode()}},
            {"type": "text", "text": OCR_PROMPT},
        ]}],
    )
    record_usage(msg.usage)
    return "".join(b.text for b in msg.content if b.type == "text").strip()


# ---------- translating ----------

def translate(client, model, text):
    if not text.strip():
        return ""
    if client is None:  # use the local `claude` CLI (Claude Pro/Max login)
        cmd = ["claude", "-p", "--tools", "", "--no-session-persistence",
               "--system-prompt", SYSTEM_PROMPT]
        if model:
            cmd += ["--model", model]
        return run_cli(cmd, input=text)
    msg = client.messages.create(
        model=model,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": text}],
    )
    record_usage(msg.usage)
    return "".join(b.text for b in msg.content if b.type == "text").strip()


def load_cache(path):
    return json.loads(path.read_text()) if path.exists() else {}


# ---------- in-place layout (text PDFs) ----------

LAYOUT_PROMPT = (
    "You are a professional book translator. The user sends numbered text blocks "
    "from one book page, each as `[n] text`. Translate every block into natural, "
    "fluent Simplified Chinese. Reply with the same markers, one translated block "
    "per marker, in the same order, and nothing else. Never merge, split, drop or "
    "renumber blocks. Sentences may run across a page break: if the first block "
    "continues a sentence from the previous page, or the last block is cut off and "
    "continues on the next page, use the given context to translate it correctly, "
    "but output only the part that appears in the numbered blocks. Never add words that are not in the block; a cut-off block stays cut off. Plain text only: no Markdown, no ** or * marks. Keep "
    "proper names consistent, and leave code, URLs and numbers as they are."
)


def extract_blocks(page):
    """Text blocks of a PDF page (pymupdf page): text, bbox and style.

    A pymupdf block is split wherever the style changes between lines or a line
    has a wide gap (labels like "Tip 1" beside a title), so each piece can be
    redrawn in its own place.
    """
    blocks = []
    for b in page.get_text("dict")["blocks"]:
        if b["type"] != 0:
            continue
        groups, cur = [], None
        for ln in b["lines"]:
            spans = [s for s in ln["spans"] if s["text"].strip()]
            if not spans:
                continue
            segs = [[spans[0]]]
            for s in spans[1:]:
                gap = s["bbox"][0] - segs[-1][-1]["bbox"][2]
                if gap > 2.5 * s["size"]:
                    segs.append([s])
                else:
                    segs[-1].append(s)
            for seg in segs:
                dom = max(seg, key=lambda s: len(s["text"].strip()))
                # size and weight only: italic or link-coloured lines stay in their paragraph
                style = (round(dom["size"] * 2), bool(dom["flags"] & 16))
                text = "".join(s["text"] for s in seg).strip()
                x0 = min(s["bbox"][0] for s in seg)
                x1 = max(s["bbox"][2] for s in seg)
                y0 = min(s["bbox"][1] for s in seg)
                y1 = max(s["bbox"][3] for s in seg)
                if cur and len(segs) == 1 and not cur["split"] and cur["style"] == style:
                    t = cur["text"]  # re-join wrapped lines, undoing line-end hyphens
                    cur["text"] = t[:-1] + text if t.endswith("-") and text[:1].islower() \
                        else t + " " + text
                    cur["bbox"] = [min(cur["bbox"][0], x0), cur["bbox"][1],
                                   max(cur["bbox"][2], x1), y1]
                    cur["lines"] += 1
                    cur["x0s"].append(x0)
                else:
                    cur = {"text": text, "bbox": [x0, y0, x1, y1], "size": dom["size"],
                           "color": "#%06x" % dom["color"], "lines": 1, "x0s": [x0],
                           "bold": bool(dom["flags"] & 16) or "bold" in dom["font"].lower(),
                           "style": style, "split": len(segs) > 1}
                    groups.append(cur)
        for g in groups:
            if re.search(r"[A-Za-z]{2}", g["text"]):  # skip page numbers, symbols
                del g["style"], g["split"]
                blocks.append(g)
    return blocks


def translate_blocks(client, model, blocks, ctx=("", "")):
    """Translate a page's blocks in one request; falls back to one by one."""
    src = "\n".join("[%d] %s" % (n, b["text"]) for n, b in enumerate(blocks, 1))
    before, after = ctx
    if before:
        src = "Context, end of the previous page (do not translate):\n%s\n\nBlocks to translate:\n%s" % (before, src)
    if after:
        src += "\n\nContext, start of the next page (do not translate):\n" + after
    for _ in range(2):
        if client is None:
            cmd = ["claude", "-p", "--tools", "", "--no-session-persistence",
                   "--system-prompt", LAYOUT_PROMPT]
            if model:
                cmd += ["--model", model]
            out = run_cli(cmd, input=src)
        else:
            msg = client.messages.create(
                model=model, max_tokens=8192, system=LAYOUT_PROMPT,
                messages=[{"role": "user", "content": src}])
            record_usage(msg.usage)
            out = "".join(b.text for b in msg.content if b.type == "text")
        parts = re.split(r"(?m)^\[(\d+)\][ \t]*", out)  # ['', '1', 'txt', '2', ...]
        got = {int(parts[k]): parts[k + 1].strip() for k in range(1, len(parts) - 1, 2)}
        if sorted(got) == list(range(1, len(blocks) + 1)):
            return [got[n].replace("**", "") for n in range(1, len(blocks) + 1)]
    return [translate(client, model, b["text"]).replace("**", "") for b in blocks]


def render_layout_page(book, page_no, blocks, zh):
    """One-page PDF (bytes): the original page with its text swapped for Chinese."""
    import fitz
    with fitz.open(str(book)) as doc:
        doc.select([page_no])
        page = doc[0]
        fills = [d["rect"] for d in page.get_drawings()
                 if d.get("fill") and d["rect"].width > 20 and d["rect"].height > 20]
        for b in blocks:
            page.add_redact_annot(fitz.Rect(b["bbox"]))
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                              graphics=fitz.PDF_REDACT_LINE_ART_NONE)
        for b, text in zip(blocks, zh):
            if not text:
                continue
            rect = fitz.Rect(b["bbox"])
            # room to grow downward (one extra line, or up to the next block)
            below = [o["bbox"][1] for o in blocks if o is not b
                     and o["bbox"][1] >= b["bbox"][3] - 1
                     and o["bbox"][0] < b["bbox"][2] and o["bbox"][2] > b["bbox"][0]]
            limit = min(below + [page.rect.y1 - 20]) - 1
            if len(b["x0s"]) > 2 and b["x0s"][1] - min(b["x0s"]) > 3 * b["size"]:
                rect.x0 = b["x0s"][1]  # text wrapped around a floated box: keep clear of it
            rect.y1 = max(rect.y1, min(rect.y1 + b["size"] * 1.4, limit),
                          rect.y0 + b["size"] * 1.6)
            center = False
            if b["lines"] == 1:  # Chinese glyphs are wide: let short lines grow rightwards
                right = [o["bbox"][0] for o in blocks if o is not b
                         and o["bbox"][0] >= b["bbox"][2]
                         and o["bbox"][1] < b["bbox"][3] and o["bbox"][3] > b["bbox"][1]]
                edge = [f.x1 - 4 for f in fills if f.contains(rect)]  # stay inside its panel
                rect.x1 = max(rect.x1, min(rect.x1 + rect.width * 0.5,
                                           min(right + edge + [page.rect.x1 - 30]) - 2))
            if b["lines"] == 1 and b["bold"]:  # a title centred inside its box/panel stays centred
                for f in fills:
                    if f.contains(rect) and abs((f.x0 + f.x1) / 2 - (rect.x0 + rect.x1) / 2) < 3 \
                            and rect.width < f.width * 0.9:
                        center = True
                        break
            html = escape(text).replace("\n", "<br>")
            size = b["size"]
            while True:  # largest size (down to 60%) at which the text fits the box
                css = ("* {font-family: sans-serif; font-size: %.1fpt; color: %s; "
                       "font-weight: %s; text-align: %s; margin: 0; line-height: 1.3;}"
                       % (size, b["color"], "bold" if b["bold"] else "normal",
                          "center" if center else "left"))
                spare, _ = page.insert_htmlbox(rect, html, css=css, scale_low=1)
                if spare >= 0:
                    break
                if size <= b["size"] * 0.6:  # give up: shrink-to-fit, any size
                    page.insert_htmlbox(rect, html, css=css, scale_low=0)
                    break
                size -= 0.5
        return doc.tobytes(garbage=3, deflate=True)


# ---------- writing ----------

def make_pdf(pages, translations, out_path, original_pdf=None, zh_pages=None):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    from pypdf import PdfReader, PdfWriter

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    margin = 20 * mm
    frame_w, frame_h = A4[0] - 2 * margin, A4[1] - 2 * margin

    def make_style(name, font, size, leading_ratio):
        return ParagraphStyle(name, fontName=font, fontSize=size,
                              leading=size * leading_ratio, spaceAfter=size * 0.9,
                              wordWrap="CJK" if font == "STSong-Light" else None)

    ascii_run = re.compile(r"[\x21-\x7e](?:[\x20-\x7e]*[\x21-\x7e])?")
    cjk = re.compile(r"[\u3400-\u9fff]")

    def mixed(line):
        # Latin/digit runs get a real Latin font plus a thin gap against
        # adjacent Chinese characters (STSong's built-in Latin is cramped).
        out, pos = [], 0
        for m in ascii_run.finditer(line):
            out.append(escape(line[pos:m.start()]))
            pad_l = " " if m.start() and cjk.match(line[m.start() - 1]) else ""
            pad_r = " " if m.end() < len(line) and cjk.match(line[m.end()]) else ""
            out.append(f"<font name='Times-Roman'>{pad_l}{escape(m.group())}{pad_r}</font>")
            pos = m.end()
        out.append(escape(line[pos:]))
        return "".join(out)

    def build_flow(text, font, size, ratio, label):
        style = make_style("body", font, size, ratio)
        head = ParagraphStyle("head", parent=style, fontSize=8, leading=10)
        flow = [Paragraph(f"<font color='#888888'>{label}</font>", head),
                Spacer(1, 4 * mm)]
        for para in text.split("\n\n") or [""]:
            body = ("<br/>".join(mixed(l) for l in para.split("\n"))
                    if font == "STSong-Light" else escape(para).replace("\n", "<br/>"))
            flow.append(Paragraph(body, style))
        return flow

    def fits(flow):
        total = 0
        for f in flow:
            _, h = f.wrap(frame_w, frame_h)
            total += h + f.getSpaceAfter()
        return total <= frame_h

    def render(text, font, ratio, label, lo=10, hi=15):
        # largest font size in [lo, hi] that still fits on one page; longer
        # text is left at `lo` and flows onto extra pages
        size = lo
        for s in range(hi * 2, lo * 2 - 1, -1):
            if fits(build_flow(text, font, s / 2, ratio, label)):
                size = s / 2
                break
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=margin,
                                rightMargin=margin, topMargin=margin,
                                bottomMargin=margin)
        doc.build(build_flow(text, font, size, ratio, label))
        return PdfReader(io.BytesIO(buf.getvalue()))

    src = PdfReader(str(original_pdf)) if original_pdf else None
    writer = PdfWriter()
    for i, text in enumerate(pages):
        if src:
            writer.add_page(src.pages[i])
        else:
            for p in render(text, "Times-Roman", 1.4, f"English — page {i + 1}").pages:
                writer.add_page(p)
        if zh_pages and i in zh_pages:
            for p in PdfReader(io.BytesIO(zh_pages[i])).pages:
                writer.add_page(p)
            continue
        if i == 0 and not translations[i]:
            # Viewers show the cover alone; no filler page, so later
            # original/translation pairs line up as two-page spreads.
            continue
        for p in render(translations[i] or "(blank page)", "STSong-Light", 1.6,
                         f"中文 — 第 {i + 1} 页").pages:
            writer.add_page(p)
    with open(out_path, "wb") as f:
        writer.write(f)


# ---------- main ----------

def parse_range(spec, total):
    if not spec:
        return list(range(total))
    a, _, b = spec.partition("-")
    start, end = int(a), int(b or a)
    return list(range(max(start, 1) - 1, min(end, total)))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("book", type=Path)
    ap.add_argument("-o", "--output", type=Path)
    ap.add_argument("--backend", choices=["claude-cli", "api"], default="claude-cli",
                    help="claude-cli uses your Claude Code login (default); "
                         "api needs ANTHROPIC_API_KEY")
    ap.add_argument("--model", help="model name (default: CLI default / %s for api)" % DEFAULT_MODEL)
    ap.add_argument("--pages", help="page range to translate, e.g. 1-20")
    ap.add_argument("--redo", help="re-translate these pages even if cached, e.g. 9-10")
    ap.add_argument("--flat", action="store_true",
                    help="PDF input: typeset the translation as plain text pages "
                         "instead of copying each page's layout")
    ap.add_argument("--ocr", action="store_true",
                    help="OCR scanned PDF pages (no text layer) with Claude vision "
                         "(works with both backends)")
    ap.add_argument("--ocr-model", help="model for OCR (default: --model / %s)" % DEFAULT_MODEL)
    args = ap.parse_args()

    pages = read_book(args.book)
    idx = parse_range(args.pages, len(pages))
    pages = [pages[i] for i in idx]
    suffix = " pages " + args.pages.replace(" ", "") if args.pages else ""
    out = args.output or args.book.with_name(f"{args.book.stem}_bilingual{suffix}.pdf")
    cache_path = out.with_suffix(".cache.json")
    cache = load_cache(cache_path)

    client = None
    if args.backend == "api":
        import anthropic
        client = anthropic.Anthropic()
        args.model = args.model or DEFAULT_MODEL

    scanned = ([n for n, t in enumerate(pages) if len(t.strip()) < MIN_TEXT_CHARS]
               if args.book.suffix.lower() == ".pdf" else [])
    if scanned and not args.ocr:
        print(f"Warning: {len(scanned)} of {len(pages)} pages have no text layer "
              "(scanned?). Re-run with --ocr to read them.", file=sys.stderr)
    elif scanned:
        ocr_path = out.with_suffix(".ocr.json")
        ocr_cache = load_cache(ocr_path)
        for n in scanned:
            key = str(idx[n])
            if key not in ocr_cache:
                print(f"OCR page {idx[n] + 1} ({scanned.index(n) + 1}/{len(scanned)})...",
                      flush=True)
                ocr_cache[key] = ocr_page(client, args.ocr_model or args.model,
                                          args.book, idx[n])
                ocr_path.write_text(json.dumps(ocr_cache, ensure_ascii=False))  # resumable
            pages[n] = ocr_cache[key]

    # text PDFs: translate block by block and redraw the original page in Chinese
    layout, ctx = {}, {}
    if args.book.suffix.lower() == ".pdf" and not args.flat:
        import fitz
        with fitz.open(str(args.book)) as doc:
            for n, i in enumerate(idx):
                if n not in scanned:
                    blocks = extract_blocks(doc[i])
                    if blocks:
                        layout[n] = blocks
                        # neighbouring pages, so sentences cut by a page break translate well
                        prev = extract_blocks(doc[i - 1]) if i > 0 else []
                        nxt = extract_blocks(doc[i + 1]) if i + 1 < len(doc) else []
                        ctx[n] = (" ".join(b["text"] for b in prev[-3:])[-600:],
                                  " ".join(b["text"] for b in nxt[:2])[:400])

    redo = set(parse_range(args.redo, len(read_book(args.book)))) if args.redo else set()
    translations = []
    for n, (i, text) in enumerate(zip(idx, pages), 1):
        key = str(i)
        if n - 1 in layout:
            key = "L" + key
            if key not in cache or i in redo or len(cache[key]) != len(layout[n - 1]):
                print(f"Translating page {i + 1} ({n}/{len(pages)})...", flush=True)
                cache[key] = translate_blocks(client, args.model, layout[n - 1],
                                                 ctx[n - 1])
                cache_path.write_text(json.dumps(cache, ensure_ascii=False))
            translations.append("")
            continue
        if key not in cache or i in redo:
            print(f"Translating page {i + 1} ({n}/{len(pages)})...", flush=True)
            cache[key] = translate(client, args.model, text)
            cache_path.write_text(json.dumps(cache, ensure_ascii=False))  # resumable
        translations.append(cache[key])

    original = None
    if args.book.suffix.lower() == ".pdf":
        # keep the original page layout; only works for the full page range
        if args.pages:
            from pypdf import PdfReader, PdfWriter
            r, w = PdfReader(str(args.book)), PdfWriter()
            for i in idx:
                w.add_page(r.pages[i])
            original = out.with_suffix(".src.pdf")
            with open(original, "wb") as f:
                w.write(f)
        else:
            original = args.book
    zh_pages = {n: render_layout_page(args.book, idx[n], blocks,
                                      cache["L%d" % idx[n]])
                for n, blocks in layout.items()}
    make_pdf(pages, translations, out, original, zh_pages)
    if original and original != args.book:
        original.unlink()
    print(f"Done: {out}")
    report_usage(out)


def report_usage(out):
    """Print this run's token usage and save it next to the output."""
    if not USAGE["calls"]:
        print("Token usage: no API calls this run (everything was cached).")
        return
    print("Token usage (this run): %d calls, %d input, %d output, "
          "%d cache-write, %d cache-read" % (
              USAGE["calls"], USAGE["input_tokens"], USAGE["output_tokens"],
              USAGE["cache_creation_input_tokens"], USAGE["cache_read_input_tokens"]))
    if USAGE["cost_usd"]:
        print("Reported cost (this run): $%.4f" % USAGE["cost_usd"])
    path = out.with_suffix(".usage.json")
    runs = json.loads(path.read_text()) if path.exists() else []
    runs.append(dict(USAGE))
    path.write_text(json.dumps(runs, indent=2))
    print(f"Usage log: {path}")


if __name__ == "__main__":
    main()
