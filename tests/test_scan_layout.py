import fitz
from booktrans.figures import ink_layer
from booktrans.layout import extract_paragraphs, render_clean_page


def make_page(items):
    """One-page PDF with (x, y, text) items in a 9pt font."""
    doc = fitz.open()
    page = doc.new_page(width=300, height=400)
    for x, y, text in items:
        page.insert_text((x, y), text, fontsize=9)
    return doc, page


def test_paragraphs_split_at_indent_and_short_last_line():
    body = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu"
    items = []
    for k in range(3):
        items.append((20 + (12 if k == 0 else 0), 50 + 12 * k, body))
    items.append((20, 86, "short last line here"))
    for k in range(3):
        items.append((20 + (12 if k == 0 else 0), 110 + 12 * k, body))
    _, page = make_page(items)
    paras = extract_paragraphs(page)
    assert [p["lines"] for p in paras] == [4, 3]
    assert paras[0]["indent"] and paras[0]["bbox"][1] < paras[1]["bbox"][1]


def test_table_becomes_cells_with_wrapped_text():
    rows = [("Metal", "Planet", "Day of week"), ("Gold", "Sun", "Sunday"),
            ("Silver", "Moon", "Monday"), ("Iron", "Mars", "Tuesday (Saxon,")]
    items = [(20, 60 + 14 * k, a) for k, (a, _, _) in enumerate(rows)]
    items += [(120, 60 + 14 * k, b) for k, (_, b, _) in enumerate(rows)]
    items += [(220, 60 + 14 * k, c) for k, (_, _, c) in enumerate(rows)]
    items.append((220, 60 + 14 * 4, "French, mardi)"))
    _, page = make_page(items)
    cells = extract_paragraphs(page)
    assert all(c["cell"] for c in cells)
    texts = [c["text"] for c in cells]
    assert "Tuesday (Saxon, French, mardi)" in texts
    assert texts[:3] == ["Metal", "Planet", "Day of week"]
    assert len(cells) == 12


def test_ink_layer_keeps_lines_and_drops_erased_text():
    import cv2
    import numpy as np
    doc, page = make_page([(30, 100, "erase me please")])
    page.draw_line((30, 200), (250, 200), width=1)
    png = ink_layer(page, [[25, 88, 140, 104]])
    img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE)
    s = 200 / 72
    assert img[int(88 * s):int(104 * s), int(25 * s):int(140 * s)].min() == 255  # text gone
    assert img[int(199 * s):int(201 * s), int(30 * s):int(250 * s)].min() < 128  # rule kept


def test_render_clean_page_skips_keep_marker(tmp_path):
    doc, page = make_page([(20, 50, "Hello world of tests"), (20, 70, "(c)")])
    blocks = extract_paragraphs(page)
    zh = ["你好世界" if "Hello" in b["text"] else "~" for b in blocks]
    path = tmp_path / "scan.pdf"
    doc.save(str(path))
    out = fitz.open("pdf", render_clean_page(path, 0, blocks, zh))
    assert "你好世界" in out[0].get_text()
