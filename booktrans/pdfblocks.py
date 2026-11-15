"""A translated PDF as blocks (see blocks.py), so it can be written in another format.

The text comes from the page layout and its cached translation; pictures, drawn figures and
tables are found on each page and put between the text where they stand.
"""
from .blocks import save_asset
from .layout import _median, has_page_image

FIGURE_DPI = 150
MIN_FIGURE = 60       # points: smaller pictures are ornaments, rules or bullets
MAX_LABEL_SHARE = 0.25  # a drawn area with more text than this is a panel of prose, not a figure


def _inside(bbox, rect):
    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    return rect[0] <= cx <= rect[2] and rect[1] <= cy <= rect[3]


def _area(r):
    return max(r[2] - r[0], 0) * max(r[3] - r[1], 0)


def _tables(page, blocks, zh):
    """[(first block position, table block, positions used)] for the tables of a page."""
    out = []
    try:
        found = page.find_tables().tables
    except Exception:  # table finding is a best effort; the text is still written as paragraphs
        return out
    for t in found:
        rows, tr_rows, used = [], [], set()
        for row in t.rows:
            cells, tr_cells = [], []
            for rect in row.cells:
                hit = [k for k, b in enumerate(blocks) if rect and k not in used and _inside(b["bbox"], rect)]
                used.update(hit)
                cells.append(" ".join(blocks[k]["text"] for k in hit))
                tr_cells.append(" ".join(zh[k] for k in hit if zh[k].strip() not in ("", "~")))
            rows.append(cells)
            tr_rows.append(tr_cells)
        filled = sum(1 for row in rows for c in row if c)
        if len(rows) >= 2 and max(len(r) for r in rows) >= 2 and filled >= 2 and used:
            out.append((min(used), {"type": "table", "rows": rows, "tr_rows": tr_rows}, used, tuple(t.bbox)))
    return out


def _figures(doc, page, blocks, tables, assets):
    """[(bbox, figure block, positions of the labels inside it)]: embedded pictures and drawn
    figures (charts, diagrams) of a page."""
    import fitz
    out = []
    page_area = _area(page.rect)
    for im in page.get_image_info(xrefs=True):
        box = im["bbox"]
        if not im.get("xref") or min(box[2] - box[0], box[3] - box[1]) < MIN_FIGURE \
                or _area(box) > 0.5 * page_area:  # a scan's page image is not a figure
            continue
        try:
            pix = fitz.Pixmap(doc, im["xref"])
            if pix.n - pix.alpha >= 4:  # CMYK
                pix = fitz.Pixmap(fitz.csRGB, pix)
            out.append((box, {"type": "figure", "alt": "", "image": save_asset(assets, pix.tobytes("png"), "png")}, set()))
        except Exception:
            continue
    try:
        clusters = page.cluster_drawings()
    except Exception:
        clusters = []
    for rect in clusters:
        box = tuple(rect)
        if min(rect.width, rect.height) < MIN_FIGURE or _area(box) > 0.7 * page_area:
            continue
        if any(_area((max(box[0], t[0]), max(box[1], t[1]), min(box[2], t[2]), min(box[3], t[3]))) > 0.3 * _area(box)
               for *_, t in tables):
            continue  # the ruling of a table
        labels = {k for k, b in enumerate(blocks) if _inside(b["bbox"], box)}
        if sum(_area(blocks[k]["bbox"]) for k in labels) > MAX_LABEL_SHARE * _area(box):
            continue
        pix = page.get_pixmap(dpi=FIGURE_DPI, clip=rect + (-2, -2, 2, 2))
        out.append((box, {"type": "figure", "alt": "", "image": save_asset(assets, pix.tobytes("png"), "png")}, labels))
    return out


def pdf_blocks(book, idx, texts, layout, zh_of, translations, assets):
    """The blocks of the chosen pages of a translated PDF.

    layout        {position: page blocks} of the pages translated block by block
    zh_of(n)      the translations of those blocks
    texts, translations   the text and translation of every other page (plain text, OCR)
    """
    import fitz
    sizes = [b["size"] for blocks in layout.values() for b in blocks for _ in range(len(b["text"]) // 20 + 1)]
    body = _median(sizes) if sizes else 0
    out = []
    with fitz.open(str(book)) as doc:
        for n, i in enumerate(idx):
            if n not in layout:
                src = [p for p in texts[n].split("\n\n") if p.strip()]
                tr = [p for p in translations[n].split("\n\n") if p.strip()]
                if len(src) == len(tr):
                    out += [{"type": "para", "text": s, "tr": t} for s, t in zip(src, tr)]
                elif texts[n].strip():
                    out.append({"type": "para", "text": texts[n].strip(), "tr": translations[n].strip()})
                continue
            page, blocks, zh = doc[i], layout[n], zh_of(n)
            tables = _tables(page, blocks, zh)
            figures = [] if has_page_image(page) else _figures(doc, page, blocks, tables, assets)
            gone = set().union(*[used for _, _, used, _ in tables], *[labels for *_, labels in figures])
            items = [(k, b) for k, b, _, _ in tables]
            for k, b in enumerate(blocks):
                if k in gone:
                    continue
                big = body and b["size"] >= 1.2 * body and b["lines"] <= 3
                item = {"type": "heading", "level": 1 if b["size"] >= 1.6 * body else 2} if big else {"type": "para"}
                item.update(text=b["text"], tr=zh[k])
                items.append((k, item))
            for box, fig, _ in figures:  # before the first text that starts below it
                after = [k for k, b in enumerate(blocks) if k not in gone and b["bbox"][1] >= box[1] - 2]
                items.append(((min(after) if after else len(blocks)) - 0.5, fig))
            out += [b for _, b in sorted(items, key=lambda it: it[0])]
    return out
