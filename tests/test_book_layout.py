"""Lines stored as blocks of their own are joined into their paragraph, and text of one
style is set at one size through the book."""
import fitz

from booktrans.layout import (book_ratios, extract_blocks, measure_layout_page,
                              render_layout_page)

LEFT, RIGHT = 72, 520


def line_pdf(path, lines, size=12, pitch=20):
    """A page whose every line is a separate text block, as some word processors write them.
    A line is (text, x0) or just text; a text that is None leaves a gap."""
    doc = fitz.open()
    page = doc.new_page()
    for k, line in enumerate(lines):
        text, x0 = line if isinstance(line, tuple) else (line, LEFT)
        if text:
            page.insert_text((x0, 100 + k * pitch), text, fontsize=size)
    doc.save(path)
    return path


def full(words):
    """`words` repeated until the line reaches the right margin."""
    text = words
    while fitz.get_text_length(text + " " + words, fontsize=12) < RIGHT - LEFT:
        text += " " + words
    return text


def blocks_of(path, page=0):
    with fitz.open(path) as doc:
        return extract_blocks(doc[page])


def sizes(pdf_bytes):
    with fitz.open("pdf", pdf_bytes) as doc:
        return {round(s["size"], 1) for b in doc[0].get_text("dict")["blocks"]
                for ln in b.get("lines", []) for s in ln["spans"] if s["text"].strip()}


def test_a_wrapped_line_in_its_own_block_joins_the_line_above(tmp_path):
    first = full("alpha beta gamma")
    (block,) = blocks_of(line_pdf(tmp_path / "w.pdf", [first, "and the rest of it."]))
    assert block["lines"] == 2 and block["text"] == first + " and the rest of it."


def test_a_line_after_a_sentence_end_or_a_page_number_starts_a_new_block(tmp_path):
    ended = full("alpha beta gamma")[:-1] + "."
    numbered = full("contents entry")[:-3] + " 12"
    assert len(blocks_of(line_pdf(tmp_path / "s.pdf", [ended, "A new paragraph here"]))) == 2
    assert len(blocks_of(line_pdf(tmp_path / "n.pdf", [numbered, "The next entry here"]))) == 2


def test_a_line_after_a_short_line_or_an_indented_line_starts_a_new_block(tmp_path):
    assert len(blocks_of(line_pdf(tmp_path / "h.pdf", ["A short heading", "Body text below it"]))) == 2
    indented = [full("alpha beta gamma"), ("a new paragraph, indented", LEFT + 24)]
    assert len(blocks_of(line_pdf(tmp_path / "i.pdf", indented))) == 2


def test_a_line_far_below_starts_a_new_block(tmp_path):
    assert len(blocks_of(line_pdf(tmp_path / "g.pdf", [full("alpha beta gamma"), None, "far below"]))) == 2


def test_book_ratio_is_what_all_but_a_few_pages_fit_at():
    fits = [{"page": {(12, False): 0.9}}] * 18 + [{"page": {(12, False): 0.6}},
                                                    {"page": {(12, False): 0.7, (20, True): 0.8}}]
    assert book_ratios(fits) == {(12, False): 0.9, (20, True): 0.8}  # 2 of 20 pages are tighter
    assert book_ratios([{"page": {(12, False): 0.9}}, {"page": {(12, False): 0.6}}]) == {(12, False): 0.6}


def test_body_text_is_one_size_on_every_page(tmp_path):
    """One page needs smaller text than the other: sized alone they differ, with the book's
    ratio they are the same."""
    doc = fitz.open()
    for _ in range(2):
        doc.new_page().insert_textbox(fitz.Rect(72, 100, 500, 160),
                                      "A body paragraph of the book that wraps over two lines "
                                      "of the page, long enough for that.", fontsize=12)
    doc.save(tmp_path / "b.pdf")
    short, long = "短译文。", "这是一段很长的译文，" * 14
    pages = [(blocks_of(tmp_path / "b.pdf", n), [zh]) for n, zh in enumerate((short, long))]
    alone = [sizes(render_layout_page(tmp_path / "b.pdf", n, b, zh)) for n, (b, zh) in enumerate(pages)]
    assert alone[0] != alone[1]
    fits = [measure_layout_page(tmp_path / "b.pdf", n, b, zh) for n, (b, zh) in enumerate(pages)]
    ratios = book_ratios(fits)
    book = [sizes(render_layout_page(tmp_path / "b.pdf", n, b, zh, fit=fits[n], book_ratio=ratios))
            for n, (b, zh) in enumerate(pages)]
    assert book[0] == book[1] and len(book[0]) == 1
