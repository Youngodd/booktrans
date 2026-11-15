import pytest
from booktrans.readers import paginate, parse_range, read_book, read_txt, reflow


def test_parse_range_all():
    assert parse_range(None, 4) == [0, 1, 2, 3]

def test_parse_range_span_and_single():
    assert parse_range("2-3", 5) == [1, 2]
    assert parse_range("2", 5) == [1]

def test_parse_range_clamps():
    assert parse_range("0-99", 3) == [0, 1, 2]

def test_parse_range_reversed_is_error():
    with pytest.raises(ValueError):
        parse_range("5-3", 10)

def test_parse_range_garbage_gives_clean_error():
    with pytest.raises(ValueError):
        parse_range("abc", 10)

def test_reflow_joins_prose_keeps_lists():
    prose = "x" * 60
    assert reflow(f"{prose}\n{prose}\n\nA\nB\nC") == f"{prose} {prose}\n\nA\nB\nC"

def test_paginate_splits_on_size():
    pages = paginate(["a" * 1000, "b" * 1000, "c" * 10])
    assert len(pages) == 2 and pages[1].startswith("b")

def test_read_txt(tmp_path):
    f = tmp_path / "a.txt"; f.write_text("one\n\ntwo")
    assert read_txt(f) == ["one\n\ntwo"]

def test_unsupported_ext(tmp_path):
    with pytest.raises(ValueError):
        read_book(tmp_path / "a.docx")


def test_a_page_this_program_redrew_is_read_and_translated_again(tmp_path):
    """Text drawn with insert_htmlbox sits inside a form, which pypdf does not read. The page
    passed for a scan with no text, so a translated PDF given back to be translated into
    another language came out unchanged."""
    import fitz
    from booktrans.pipeline import translate_book
    from booktrans.readers import read_book
    from tests.conftest import FakeBackend
    doc = fitz.open()
    for n in range(2):
        doc.new_page().insert_htmlbox(fitz.Rect(72, 80, 500, 300),
                                      f"An English paragraph on page {n}, drawn the way this program draws a translated page.")
    doc.save(tmp_path / "book_en.pdf")
    pages = read_book(tmp_path / "book_en.pdf")
    assert all("English paragraph" in p for p in pages)
    backend = FakeBackend()
    out = translate_book(tmp_path / "book_en.pdf", tmp_path / "o.pdf", backend,
                         target="zh-CN", output_mode="target-only", auto_glossary=False)
    assert len(backend.calls) == 2
    with fitz.open(out) as d:
        text = "".join(p.get_text() for p in d)
    assert "译" in text and "English paragraph" not in text
