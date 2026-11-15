"""Suggested settings come from the file alone, each with a reason, and never fail."""
import fitz

from booktrans.recommend import recommend


def test_a_text_pdf_keeps_its_format_and_needs_no_ocr(text_pdf):
    got = recommend(text_pdf, total=3, language="en")
    s = got["settings"]
    assert s["source"] == "en" and s["ocr"] is False and s["output_format"] == "pdf"
    assert s["output_mode"] == "bilingual" and "pages" not in s and "target" not in s
    assert set(got["reasons"]) == set(s) and all(r["en"].endswith(".") and r["zh"].endswith("。") for r in got["reasons"].values())


def test_a_pdf_without_a_text_layer_needs_ocr(tmp_path):
    doc = fitz.open()
    for _ in range(4):
        doc.new_page()
    doc.save(tmp_path / "scan.pdf")
    got = recommend(tmp_path / "scan.pdf", total=4)
    assert got["settings"]["ocr"] is True and "4 of 4" in got["reasons"]["ocr"]["en"]
    assert "source" not in got["settings"]  # the language is not known: nothing is suggested


def test_a_long_book_gets_a_trial_range_and_a_names_check(tmp_path):
    s = recommend(tmp_path / "b.epub", total=346, language="en")["settings"]
    assert s["pages"] == "1-10" and s["review_names"] is True and s["output_format"] == "epub"
    assert "review_names" not in recommend(tmp_path / "b.epub", total=346, language="ja")["settings"]


def test_a_chinese_book_is_not_translated_into_chinese(tmp_path):
    assert recommend(tmp_path / "b.docx", total=5, language="zh-CN")["settings"]["target"] == "en"
    assert recommend(tmp_path / "b.md", total=5, language="fr")["settings"]["output_format"] == "md"


def test_an_unreadable_file_still_gets_an_answer(tmp_path):
    (tmp_path / "bad.pdf").write_bytes(b"not a pdf")
    got = recommend(tmp_path / "bad.pdf")
    assert "ocr" not in got["settings"] and got["settings"]["output_format"] == "pdf"
