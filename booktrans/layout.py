"""In-place layout for text PDFs: find text blocks, redraw the page in Chinese."""
import re
from xml.sax.saxutils import escape


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


def has_page_image(page):
    """True if a single image covers most of the page (a scan)."""
    area = page.rect.width * page.rect.height
    return any((im["bbox"][2] - im["bbox"][0]) * (im["bbox"][3] - im["bbox"][1]) > 0.5 * area
               for im in page.get_image_info())


def paper_color(page, bbox):
    """Median colour (0-1 RGB) inside bbox: the paper, since ink is the minority."""
    import fitz
    pix = page.get_pixmap(dpi=72, clip=fitz.Rect(bbox), colorspace=fitz.csRGB)
    chans = [sorted(pix.samples[c::pix.n]) for c in range(3)]
    return tuple(ch[len(ch) // 2] / 255 for ch in chans)


def render_layout_page(book, page_no, blocks, zh):
    """One-page PDF (bytes): the original page with its text swapped for Chinese."""
    import fitz
    with fitz.open(str(book)) as doc:
        doc.select([page_no])
        page = doc[0]
        fills = [d["rect"] for d in page.get_drawings()
                 if d.get("fill") and d["rect"].width > 20 and d["rect"].height > 20]
        scanned = has_page_image(page)
        paper = [paper_color(page, b["bbox"]) for b in blocks] if scanned else []
        for k, b in enumerate(blocks):
            rect = fitz.Rect(b["bbox"])
            if scanned:  # the English is printed in the scan: paint it out
                page.add_redact_annot(rect + (-1, -1, 1, 1), fill=paper[k])
            else:
                page.add_redact_annot(rect)
        page.apply_redactions(
            images=fitz.PDF_REDACT_IMAGE_PIXELS if scanned else fitz.PDF_REDACT_IMAGE_NONE,
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


def collect_layout(book, idx, skip=()):
    """Blocks and neighbour-page context for each page n of `idx` not in `skip`.

    Returns (layout, ctx) dicts keyed by position n in `idx`.
    """
    import fitz
    layout, ctx = {}, {}
    with fitz.open(str(book)) as doc:
        for n, i in enumerate(idx):
            if n in skip:
                continue
            blocks = extract_blocks(doc[i])
            if blocks:
                layout[n] = blocks
                # neighbouring pages, so sentences cut by a page break translate well
                prev = extract_blocks(doc[i - 1]) if i > 0 else []
                nxt = extract_blocks(doc[i + 1]) if i + 1 < len(doc) else []
                ctx[n] = (" ".join(b["text"] for b in prev[-3:])[-600:],
                          " ".join(b["text"] for b in nxt[:2])[:400])
    return layout, ctx
