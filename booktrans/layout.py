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


def _join(text, new):
    """Join wrapped lines, undoing a line-end hyphen."""
    if text.endswith("-") and new[:1].islower():
        return text[:-1] + new
    return text + " " + new


def _median(values):
    values = sorted(values)
    return values[len(values) // 2]


def _scan_rows(page):
    """Text rows of a scan: chunks on one baseline, split into segments at wide gaps.

    A segment is a run of text with only word-sized gaps; a table row has several.
    Segments without real words (symbols, OCR noise) are left out: their ink stays.
    """
    chunks = []
    for b in page.get_text("dict")["blocks"]:
        if b["type"] != 0:
            continue
        for ln in b["lines"]:
            spans = [s for s in ln["spans"] if s["text"].strip()]
            if spans:
                dom = max(spans, key=lambda s: len(s["text"].strip()))
                chunks.append({"bbox": list(ln["bbox"]), "size": dom["size"],
                               "color": dom["color"],
                               "words": [(w["bbox"][0], w["bbox"][2], w["text"].strip())
                                         for w in spans],
                               "bold": bool(dom["flags"] & 16) or "bold" in dom["font"].lower(),
                               "text": "".join(s["text"] for s in spans).strip()})
    if not chunks:
        return [], 0
    em = _median([c["size"] for c in chunks])
    chunks.sort(key=lambda c: (c["bbox"][1] + c["bbox"][3]) / 2)
    grouped = []  # chunks on the same text row (e.g. "xxii" + "- Introduction")
    for c in chunks:
        yc = (c["bbox"][1] + c["bbox"][3]) / 2
        if grouped and abs(yc - grouped[-1]["yc"]) < 0.4 * (c["bbox"][3] - c["bbox"][1]):
            grouped[-1]["parts"].append(c)
            grouped[-1]["yc"] = (grouped[-1]["yc"] + yc) / 2
        else:
            grouped.append({"parts": [c], "yc": yc})
    rows = []
    for g in grouped:
        segs = []
        for c in sorted(g["parts"], key=lambda c: c["bbox"][0]):
            if segs and c["bbox"][0] - segs[-1][-1]["bbox"][2] <= 2 * em:
                segs[-1].append(c)
            else:
                segs.append([c])
        segs = [{"text": " ".join(c["text"] for c in s),
                 "words": [w for c in s for w in c["words"]],
                 "x0": min(c["bbox"][0] for c in s), "x1": max(c["bbox"][2] for c in s),
                 "y0": min(c["bbox"][1] for c in s), "y1": max(c["bbox"][3] for c in s),
                 "size": max(s, key=lambda c: len(c["text"]))["size"],
                 "color": max(s, key=lambda c: len(c["text"]))["color"],
                 "bold": max(s, key=lambda c: len(c["text"]))["bold"]} for s in segs]
        segs = [s for s in segs if re.search(r"[A-Za-z]{2}", s["text"])]
        if not segs:
            continue
        dom = max(segs, key=lambda s: len(s["text"]))
        rows.append({"segs": segs, "text": " ".join(s["text"] for s in segs),
                     "x0": segs[0]["x0"], "x1": segs[-1]["x1"],
                     "y0": min(s["y0"] for s in segs), "y1": max(s["y1"] for s in segs),
                     "size": dom["size"], "color": dom["color"], "bold": dom["bold"]})
    return rows, em


def _starts(row, em):
    """x positions where a run of words begins after a gap: candidate column starts."""
    words = sorted(w for seg in row["segs"] for w in seg["words"])
    return [w[0] for k, w in enumerate(words) if k == 0 or w[0] - words[k - 1][1] >= 0.7 * em]


def _find_tables(rows, em):
    """Row ranges (first, last, column x positions) that look like tables.

    A table is three or more nearby rows that each have several segments, whose
    runs of words start at the same x positions in at least two columns.
    """
    multi = [k for k, r in enumerate(rows) if len(r["segs"]) >= 2]
    tables, i = [], 0
    while i < len(multi):
        j = i
        while j + 1 < len(multi) and multi[j + 1] - multi[j] <= 5:
            j += 1
        grp, i = multi[i:j + 1], j + 1
        if len(grp) < 3:
            continue
        clusters = []
        for x in sorted(x for k in grp for x in _starts(rows[k], em)):
            if clusters and x - clusters[-1][-1] <= 0.8 * em:
                clusters[-1].append(x)
            else:
                clusters.append([x])
        cols = [_median(c) for c in clusters if len(c) >= max(2, 0.4 * len(grp))]
        if len(cols) < 2:
            continue
        last = grp[-1]
        while (last + 1 < len(rows) and len(rows[last + 1]["segs"]) == 1  # wrapped cell text
               and any(abs(rows[last + 1]["x0"] - c) < 1.2 * em for c in cols[1:])
               and rows[last + 1]["y0"] - rows[last]["y1"] < em):
            last += 1
        tables.append((grp[0], last, cols))
    return tables


def _table_cells(rows, cols, em, right):
    """Cell blocks of one table.

    Each line is cut into pieces at the column starts. A line starts a new table
    row when it has a first-column piece and others beside it, unless it reads as
    wrapped text: the line above ended mid-phrase, or its first piece starts with
    "(" or a lowercase letter. Other lines are wrapped text of the cells above.
    """
    def col_of(x):
        d, n = min((abs(x - c), n) for n, c in enumerate(cols))
        return n if d <= 1.2 * em else None

    def pieces(seg):
        out, cur = [], []
        for w in seg["words"]:
            if cur and w[0] - cur[-1][1] >= 0.7 * em and col_of(w[0]) is not None \
                    and col_of(w[0]) != col_of(cur[0][0]):
                out.append(cur)
                cur = []
            cur.append(w)
        out.append(cur)
        res = [dict(seg, text=" ".join(w[2] for w in c), x0=c[0][0], x1=c[-1][1]) for c in out]
        return [p for p in res if re.search(r"[A-Za-z]{2}", p["text"])]

    cells, ri, tail = {}, -1, ""
    for r in rows:
        ps = sorted((p for seg in r["segs"] for p in pieces(seg)), key=lambda p: p["x0"])
        first = [p for p in ps if col_of(p["x0"]) == 0]
        wrapped = tail.endswith((",", ";", "=", "(", "-")) or \
            bool(first and (first[0]["text"][0] == "(" or first[0]["text"][0].islower()))
        if ri < 0 or (len(ps) >= 2 and first and not wrapped):
            ri += 1
        for p in ps:
            c = col_of(p["x0"])
            cells.setdefault((ri, c if c is not None else -1 - int(p["x0"])), []).append(p)
        if ps:
            tail = ps[-1]["text"]
    blocks = []
    for (ri, c), segs in sorted(cells.items(), key=lambda kv: (kv[0][0], kv[1][0]["x0"])):
        text = segs[0]["text"]
        for s in segs[1:]:
            text = _join(text, s["text"])
        x0, x1 = min(s["x0"] for s in segs), max(s["x1"] for s in segs)
        nxt = [cx for cx in cols if cx > x0 + em]
        blocks.append({"text": text, "bbox": [x0, segs[0]["y0"], x1, segs[-1]["y1"]],
                       "size": _median([s["size"] for s in segs]), "color": "#%06x" % segs[0]["color"],
                       "lines": len(segs), "x0s": [s["x0"] for s in segs], "bold": segs[0]["bold"],
                       "indent": False, "cell": True,
                       "colr": max(x1, (min(nxt) - 0.6 * em) if nxt else right),
                       "rects": [[s["x0"], s["y0"], s["x1"], s["y1"]] for s in segs]})
    return blocks


def extract_paragraphs(page):
    """Blocks of a scanned page, same format as extract_blocks.

    The scan's text layer has noisy font sizes and word gaps, so lines are
    merged by geometry instead: a new paragraph starts at a first-line indent,
    after a short last line, after a vertical gap, or where the size jumps.
    Tables become one block per cell (their column positions are kept).
    """
    rows, em = _scan_rows(page)
    if not rows:
        return []
    tables = {t[0]: t for t in _find_tables(rows, em)}
    in_table = {k for a, b, _ in tables.values() for k in range(a, b + 1)}
    plain = [r for k, r in enumerate(rows) if k not in in_table] or rows
    em = _median([r["size"] for r in plain])  # typical body size
    right = _median([r["x1"] for r in plain])
    paras, cur, k = [], None, 0
    while k < len(rows):
        if k in tables:
            a, b, cols = tables[k]
            paras.extend(_table_cells(rows[a:b + 1], cols, em, max(r["x1"] for r in plain)))
            cur, k = None, b + 1
            continue
        r = rows[k]
        near = sorted(o["x0"] for o in plain if abs(o["y0"] - r["y0"]) < 3 * 1.5 * em)
        left = _median(near) if near else r["x0"]  # local left margin: robust to a skewed scan
        indent = r["x0"] - left > 0.75 * em
        new = cur is None
        if cur is not None:
            prev = rows[k - 1]
            new = (indent or prev["x1"] < right - 2 * em or r["y0"] - prev["y1"] > 0.8 * em
                   or abs(r["size"] / prev["size"] - 1) > 0.25 or r["bold"] != prev["bold"])
        rect = [s for s in ([x["x0"], x["y0"], x["x1"], x["y1"]] for x in r["segs"])]
        if new:
            cur = {"text": r["text"], "bbox": [r["x0"], r["y0"], r["x1"], r["y1"]],
                   "sizes": [r["size"]], "color": "#%06x" % r["color"], "lines": 1,
                   "x0s": [r["x0"]], "bold": r["bold"], "indent": indent, "rects": rect}
            paras.append(cur)
        else:
            cur["text"] = _join(cur["text"], r["text"])
            cur["bbox"] = [min(cur["bbox"][0], r["x0"]), cur["bbox"][1],
                           max(cur["bbox"][2], r["x1"]), r["y1"]]
            cur["lines"] += 1
            cur["x0s"].append(r["x0"])
            cur["sizes"].append(r["size"])
            cur["rects"] += rect
        k += 1
    for p in paras:
        if "sizes" in p:
            p["size"] = _median(p.pop("sizes"))
    return paras


def page_blocks(page):
    return extract_paragraphs(page) if has_page_image(page) else extract_blocks(page)


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


KEEP = "~"  # the translator's answer for a block that is a symbol or OCR noise: keep its ink


def render_clean_page(book, page_no, blocks, zh):
    """One-page PDF (bytes) for a scan: a clean white page with the Chinese text.

    The page's lines, curves and symbols are kept as clean ink (figures.ink_layer);
    the English text is dropped and its Chinese drawn on top. Each paragraph starts
    at the height of its English paragraph and its bottom is free; table cells sit
    in their original columns. One size factor per group keeps sizes consistent.
    """
    import fitz
    from .figures import ink_layer
    drawn = [(b, t.strip()) for b, t in zip(blocks, zh) if t.strip() not in ("", KEEP)]
    with fitz.open(str(book)) as src:
        pr = src[page_no].rect
        ink = ink_layer(src[page_no], [r for b, _ in drawn for r in b.get("rects", [b["bbox"]])])
    doc = fitz.open()
    page = doc.new_page(width=pr.width, height=pr.height)
    page.insert_image(page.rect, stream=ink)
    body = [b for b in blocks if b["lines"] >= 3 and not b.get("cell")] \
        or [b for b in blocks if not b.get("cell")] or blocks
    em = _median([b["size"] for b in body])
    left = min(min(b["x0s"]) for b in body)
    right = max(b["bbox"][2] for b in body)

    items = []
    for b, text in drawn:
        rel = b["size"] / em
        rel = 1.0 if 0.88 <= rel <= 1.12 else min(max(rel, 0.75), 1.5)
        x0, y0, x1, _ = b["bbox"]
        x0 = min(b["x0s"])
        below = [o["bbox"][1] for o in blocks if o is not b and o["bbox"][1] >= b["bbox"][3] - 1
                 and o["bbox"][0] < x1 and o["bbox"][2] > x0]
        limit = min(below + [pr.y1 - 20]) - 2
        center = False
        if b.get("cell"):
            x1 = b["colr"]
        elif b["lines"] == 1:  # a short line may grow rightwards; a centred one stays centred
            if abs((x0 + x1) / 2 - (left + right) / 2) < 8 and x1 - x0 < 0.8 * (right - left):
                x0, x1, center = left, right, True
            else:
                beside = [o["bbox"][0] - 3 for o in blocks if o is not b and o["bbox"][0] >= x1 - 1
                          and o["bbox"][1] < b["bbox"][3] and o["bbox"][3] > b["bbox"][1]]
                x1 = max(x1, min(beside + [right]))
        items.append((b, text, rel, fitz.Rect(x0, y0 - 1, x1, max(limit, y0 + em * 1.6)), center))

    def draw(pg, b, text, rel, rect, center, f):
        flow = b["lines"] >= 3 and not b.get("cell")
        css = ("* {font-family: sans-serif; font-size: %.2fpt; color: %s; font-weight: %s; "
               "text-align: %s; text-indent: %s; margin: 0; line-height: %.2f;}"
               % (em * rel * f, b["color"], "bold" if b["bold"] else "normal",
                  "center" if center else "justify" if flow else "left",
                  "2em" if b.get("indent") and b["lines"] >= 2 else "0", 1.5 if flow else 1.3))
        return pg.insert_htmlbox(rect, escape(text).replace("\n", "<br>"), css=css, scale_low=1)

    scratch = fitz.open().new_page(width=pr.width, height=pr.height)
    factor = {}
    for cell in (False, True):  # table cells shrink on their own, not the whole page
        group = [it for it in items if bool(it[0].get("cell")) == cell]
        f = 1.1
        while f > 0.6 and not all(draw(scratch, *it, f)[0] >= 0 for it in group):
            f -= 0.02
        factor[cell] = f
    for it in items:
        if draw(page, *it, factor[bool(it[0].get("cell"))])[0] < 0:  # shrink to fit
            print("Warning: page %d: a paragraph is too long for its space" % (page_no + 1))
            page.insert_htmlbox(it[3], escape(it[1]), scale_low=0)
    doc.subset_fonts()  # every htmlbox embeds the whole CJK font; keep only the glyphs used
    return doc.tobytes(garbage=4, deflate=True)


def render_layout_page(book, page_no, blocks, zh):
    """One-page PDF (bytes): the original page with its text swapped for Chinese."""
    import fitz
    if "indent" in blocks[0]:  # paragraph blocks of a scan
        return render_clean_page(book, page_no, blocks, zh)
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
        doc.subset_fonts()
        return doc.tobytes(garbage=4, deflate=True)


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
            blocks = page_blocks(doc[i])
            if blocks:
                layout[n] = blocks
                # neighbouring pages, so sentences cut by a page break translate well
                prev = page_blocks(doc[i - 1]) if i > 0 else []
                nxt = page_blocks(doc[i + 1]) if i + 1 < len(doc) else []
                ctx[n] = (" ".join(b["text"] for b in prev[-3:])[-600:],
                          " ".join(b["text"] for b in nxt[:2])[:400])
    return layout, ctx
