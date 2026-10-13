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
