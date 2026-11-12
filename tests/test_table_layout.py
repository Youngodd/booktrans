"""Text PDFs: cells side by side on one row are separate blocks, wrapped lines still join."""
import re

import fitz

from booktrans.layout import extract_blocks
from booktrans.pipeline import translate_book
from tests.conftest import FakeBackend

ROWS = [("Hong Kong", "hk-hon.pvdata.host"), ("Hungary - Budapest", "hu-bud.pvdata.host"),
        ("Iceland - Reykjavik", "is-rey.pvdata.host"), ("New Zealand - Auckland", "nz-auc.pvdata.host")]


def table_pdf(path, rows=ROWS, centered=True):
    """A two-column table with ruled cells, text centred in each cell like a printed web page."""
    doc = fitz.open()
    page = doc.new_page()
    x = (50, 300, 550)
    for r, (a, b) in enumerate(rows):
        y = 80 + r * 30
        for c, text in enumerate((a, b)):
            rect = fitz.Rect(x[c], y - 20, x[c + 1], y + 10)
            page.draw_rect(rect, color=(0.8, 0.8, 0.8))
            w = fitz.get_text_length(text, fontsize=12)
            left = rect.x0 + (rect.width - w) / 2 if centered else rect.x0 + 8
            page.insert_text((left, y), text, fontsize=12)
    doc.save(path)
    return path


def test_each_table_cell_is_its_own_block(tmp_path):
    page = fitz.open(table_pdf(tmp_path / "t.pdf"))[0]
    blocks = extract_blocks(page)
    assert sorted(b["text"] for b in blocks) == sorted(t for row in ROWS for t in row)
    for b in blocks:
        assert b["lines"] == 1
    left = [b for b in blocks if b["text"] in [r[0] for r in ROWS]]
    right = [b for b in blocks if b["text"] in [r[1] for r in ROWS]]
    assert max(b["bbox"][2] for b in left) < min(b["bbox"][0] for b in right)   # no block spans both columns


def test_left_aligned_cells_are_separate_too(tmp_path):
    page = fitz.open(table_pdf(tmp_path / "t.pdf", centered=False))[0]
    assert len(extract_blocks(page)) == 2 * len(ROWS)


def test_a_wrapped_paragraph_is_still_one_block(tmp_path):
    doc = fitz.open()
    page = doc.new_page()
    text = "This is a body paragraph of the book that is long enough to wrap across several lines on the page."
    page.insert_textbox(fitz.Rect(72, 100, 300, 300), text, fontsize=11)
    doc.save(tmp_path / "p.pdf")
    blocks = extract_blocks(fitz.open(tmp_path / "p.pdf")[0])
    assert len(blocks) == 1 and blocks[0]["lines"] >= 3 and blocks[0]["text"].startswith("This is a body")


def test_a_wrapped_cell_beside_a_short_cell_keeps_its_lines_together(tmp_path):
    doc = fitz.open()
    page = doc.new_page()
    long = "A long description in the left cell that wraps onto a second and a third line."
    page.insert_textbox(fitz.Rect(60, 100, 230, 200), long, fontsize=11)
    page.insert_text((320, 112), "short.value", fontsize=11)
    doc.save(tmp_path / "w.pdf")
    blocks = extract_blocks(fitz.open(tmp_path / "w.pdf")[0])
    texts = sorted(b["text"] for b in blocks)
    assert texts == sorted([long, "short.value"]) or (len(blocks) == 2 and any(b["lines"] >= 2 for b in blocks))
    assert not any("short.value" in b["text"] and "description" in b["text"] for b in blocks)


def test_heading_between_paragraph_lines_does_not_reattach(tmp_path):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "First paragraph line one of the text here.", fontsize=11)
    page.insert_text((72, 114), "First paragraph line two of the text here.", fontsize=11)
    page.insert_text((72, 140), "A HEADING", fontsize=20)
    page.insert_text((72, 170), "Second paragraph starts here with words.", fontsize=11)
    doc.save(tmp_path / "h.pdf")
    texts = [b["text"] for b in extract_blocks(fitz.open(tmp_path / "h.pdf")[0])]
    assert texts == ["First paragraph line one of the text here. First paragraph line two of the text here.",
                     "A HEADING", "Second paragraph starts here with words."]


def test_the_translated_cells_stay_in_their_own_columns(tmp_path):
    def reply(user):
        return "\n".join(f"[{m.group(1)}] 译：{m.group(2)}" for m in re.finditer(r"(?m)^\[(\d+)\] (.*)$", user))
    book = table_pdf(tmp_path / "t.pdf")
    out = translate_book(book, tmp_path / "o.pdf", FakeBackend(reply=reply), auto_glossary=False,
                         source="en", output_mode="target-only")
    page = fitz.open(out)[0]
    for a, b in ROWS:
        left, right = page.search_for("译：" + a), page.search_for("译：" + b)
        assert left and right, (a, b)
        assert left[0].x1 < 300 <= right[0].x0, (a, b, left[0], right[0])      # each in its own column
        assert abs(left[0].y0 - right[0].y0) < 3                              # on the same row
