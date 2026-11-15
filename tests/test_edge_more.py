"""More edge cases (docs/edge-case-test-plan.md, areas 2, 3 and 7): EPUB structure, PDFs of odd shape
written in other formats, scanned pages and OCR that fails, the recommendation, language detection."""
import zipfile

import fitz
import pytest
from ebooklib import epub

from booktrans import languages
from booktrans.backends.base import BackendError
from booktrans.blockreaders import read_blocks
from booktrans.options import JobOptions
from booktrans.pipeline import translate_book
from booktrans.recommend import recommend
from tests.conftest import FakeBackend


def png_bytes():
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 12, 12), False)
    pix.set_rect(pix.irect, (200, 40, 40))
    return pix.tobytes("png")


def make_epub(path, chapters, images=None, lang="en"):
    b = epub.EpubBook()
    b.set_identifier("test-id")
    b.set_title("Test book")
    b.set_language(lang)
    items = []
    for i, html in enumerate(chapters):
        c = epub.EpubHtml(title=f"c{i}", file_name=f"c{i}.xhtml", lang=lang, content=html)
        b.add_item(c)
        items.append(c)
    for name, data in (images or {}).items():
        b.add_item(epub.EpubItem(uid=name, file_name=name, media_type="image/png", content=data))
    b.spine = items
    b.add_item(epub.EpubNcx())
    b.add_item(epub.EpubNav())
    epub.write_epub(str(path), b)
    return path


def run(book, out, backend=None, **kw):
    kw.setdefault("auto_glossary", False)
    backend = backend or FakeBackend()
    translate_book(book, out, backend, JobOptions(**kw))
    return backend


# ---------------------------------------------------------------- EPUB

def test_an_epub_with_only_pictures_or_empty_chapters_has_nothing_to_translate(tmp_path):
    only_images = make_epub(tmp_path / "img.epub", ['<html><body><img src="a.png"/></body></html>'], {"a.png": png_bytes()})
    empty = make_epub(tmp_path / "empty.epub", ["<html><body><p> </p></body></html>"])
    for book in (only_images, empty):
        with pytest.raises(ValueError, match="no pages"):
            run(book, tmp_path / "o.docx", output_format="docx")


def test_epub_pictures_that_leave_the_archive_or_live_on_the_web_are_not_followed(tmp_path):
    book = make_epub(tmp_path / "t.epub", ['<html><body><p>Hello text here.</p><img src="../../../../etc/hosts"/>'
                                           '<img src="http://x.test/y.png"/><img src="data:image/png;base64,AAAA"/>'
                                           '</body></html>'])
    found = read_blocks(book, tmp_path / "assets")
    assert [b["type"] for b in found] == ["para"]
    assert not (tmp_path / "assets").exists() or not list((tmp_path / "assets").iterdir())


STRUCTURE = ('<html><body><h1>Title</h1><p>Para with <b>bold</b> and <i>italic</i>.</p>'
             '<ul><li>a</li><li>b<ul><li>nested</li></ul></li></ul>'
             '<table><tr><td>c1</td><td>c2</td></tr></table><pre>code stays</pre></body></html>')


@pytest.mark.parametrize("fmt", ["epub", "docx", "md", "pdf"])
@pytest.mark.parametrize("mode", ["bilingual", "target-only"])
def test_an_epub_with_lists_tables_and_code_goes_to_every_format(tmp_path, fmt, mode):
    book = make_epub(tmp_path / "t.epub", [STRUCTURE])
    sent = run(book, tmp_path / f"o.{fmt}", output_format=fmt, output_mode=mode)
    assert (tmp_path / f"o.{fmt}").stat().st_size > 0
    assert all("code stays" not in c for c in sent.calls)  # code is never sent to the model


def test_an_epub_written_back_into_itself_can_be_written_again_from_the_cache(tmp_path):
    book = make_epub(tmp_path / "t.epub", [STRUCTURE, "<html><body><h1>Two</h1><p>Second chapter.</p></body></html>"])
    run(book, tmp_path / "o.epub", output_format="epub")
    again = run(book, tmp_path / "o2.epub", output_format="epub", output_mode="target-only", state=tmp_path / "o.epub")
    assert again.calls == []
    with zipfile.ZipFile(tmp_path / "o2.epub") as z:
        assert z.testzip() is None


def test_an_arabic_epub_is_read_and_translated(tmp_path):
    book = make_epub(tmp_path / "ar.epub", ['<html><body><p>مرحبا بالعالم هذا كتاب</p></body></html>'], lang="ar")
    sent = run(book, tmp_path / "o.md", output_format="md", target="en")
    assert "مرحبا" in sent.calls[0] and "مرحبا" in (tmp_path / "o.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("html,text", [
    ("<p>Para with <b>bold</b> and <i>italic</i>.</p>", "Para with bold and italic."),
    ('<p><span class="dropcap">T</span>he story begins</p>', "The story begins"),
    ("<p>你好<b>世界</b>。</p>", "你好世界。"),
    ("<p>first line<br/>second line</p>", "first line second line"),
    ("<p>one<br>two</p>", "one two"),
    ("<p><ruby>漢<rt>kan</rt></ruby><ruby>字<rt>ji</rt></ruby>を読む</p>", "漢字を読む"),
    ("<p>  lots \n of \t space  </p>", "lots of space"),
    ("<p><a href='#x'>link</a>, then <em>more</em>!</p>", "link, then more!"),
    ("<p>caf&eacute; &amp; cr&egrave;me &lt;b&gt;</p>", "café & crème <b>"),
    ("<p>a<!-- a comment -->b</p>", "ab"),
])
def test_epub_paragraph_text_is_read_as_a_reader_sees_it(tmp_path, html, text):
    book = make_epub(tmp_path / "t.epub", [f"<html><body>{html}<p>padding paragraph</p></body></html>"])
    found = read_blocks(book, tmp_path / "assets")
    assert found[0]["text"] == text


def test_inline_tags_with_no_space_between_them_make_no_space():
    from bs4 import BeautifulSoup
    from booktrans.readers import html_text
    soup = BeautifulSoup("<p><b>Hello</b><i>world</i><span>!</span></p><div>a</div><div>b</div>", "html.parser")
    assert html_text(soup.p) == "Helloworld!"  # the page shows no space either
    assert html_text(soup) == "Helloworld! a b"  # blocks are apart
    assert html_text(soup.p, skip=("i",)) == "Hello!"


def test_epub_list_items_and_table_cells_keep_inline_text_together(tmp_path):
    book = make_epub(tmp_path / "t.epub", ['<html><body><ul><li><b>Bold</b>, plain<ul><li>in<i>ner</i></li></ul></li></ul>'
                                           '<table><tr><td><b>c</b>ell, one</td><td>two</td></tr></table></body></html>'])
    found = read_blocks(book, tmp_path / "assets")
    assert [b.get("text") for b in found[:2]] == ["Bold, plain", "inner"]
    assert found[2]["rows"] == [["cell, one", "two"]]


def test_an_epub_written_back_into_itself_keeps_its_line_breaks_and_inline_marks(tmp_path):
    book = make_epub(tmp_path / "t.epub", ["<html><body><p>first<br/>second <b>bold</b>.</p></body></html>"])
    run(book, tmp_path / "o.epub", output_format="epub")
    with zipfile.ZipFile(tmp_path / "o.epub") as z:
        html = "".join(z.read(n).decode("utf-8") for n in z.namelist() if n.endswith("c0.xhtml"))
    assert "<br" in html and "<b>bold</b>" in html


# ---------------------------------------------------------------- PDFs of odd shape, written in other formats

@pytest.fixture
def blank_pdf(tmp_path):
    d = fitz.open()
    for _ in range(3):
        d.new_page()
    d.save(tmp_path / "blank.pdf")
    return tmp_path / "blank.pdf"


@pytest.fixture
def odd_pdf(tmp_path):
    d = fitz.open()
    p = d.new_page()
    p.insert_text((72, 100), "Rotated page text here for the test.", fontsize=14)
    p.set_rotation(90)
    d.new_page().insert_image(fitz.Rect(50, 50, 300, 300), stream=png_bytes())
    d.save(tmp_path / "odd.pdf")
    return tmp_path / "odd.pdf"


@pytest.mark.parametrize("fmt", ["pdf", "md", "docx", "epub"])
def test_a_pdf_with_no_text_at_all_is_written_without_a_crash(tmp_path, blank_pdf, fmt):
    out = tmp_path / f"o.{fmt}"
    try:
        run(blank_pdf, out, output_format=fmt)
    except ValueError as e:  # nothing to translate may be reported, but as a message
        assert "no pages" in str(e) or "Nothing" in str(e)
    else:
        assert out.is_file()


@pytest.mark.parametrize("fmt", ["pdf", "md", "docx", "epub"])
def test_a_rotated_page_and_a_picture_only_page_are_written(tmp_path, odd_pdf, fmt):
    out = tmp_path / f"o.{fmt}"
    run(odd_pdf, out, output_format=fmt)
    assert out.is_file() and out.stat().st_size > 0


def test_a_long_pdf_is_done_in_a_reasonable_time(tmp_path):
    import time
    d = fitz.open()
    for i in range(150):
        d.new_page().insert_textbox(fitz.Rect(72, 72, 500, 700), f"Page {i}. " + "Body text that wraps across lines. " * 15, fontsize=11)
    d.save(tmp_path / "big.pdf")
    start = time.time()
    sent = run(tmp_path / "big.pdf", tmp_path / "big.md", output_format="md")
    assert len(sent.calls) == 150 and time.time() - start < 60
    assert (tmp_path / "big.md").read_text(encoding="utf-8").count("Page ") >= 150


# ---------------------------------------------------------------- scanned pages and OCR that fails

class Vision(FakeBackend):
    supports_vision = True

    def __init__(self, fail_on=None):
        super().__init__()
        self.fail_on = fail_on
        self.read = []

    def ocr_image(self, jpeg, prompt):
        self.read.append(len(self.read))
        if self.fail_on is not None and len(self.read) == self.fail_on:
            raise BackendError("the vision model is not reachable")
        return f"Scanned text on page number {len(self.read)} of the book."


@pytest.fixture
def scan(tmp_path):
    d = fitz.open()
    for _ in range(3):
        d.new_page()
    d.save(tmp_path / "scan.pdf")
    return tmp_path / "scan.pdf"


def test_ocr_that_fails_part_way_resumes_with_only_the_pages_not_yet_read(tmp_path, scan, monkeypatch):
    from booktrans.backends import base
    monkeypatch.setattr(base.time, "sleep", lambda s: None)
    first = Vision(fail_on=2)
    with pytest.raises(BackendError):
        translate_book(scan, tmp_path / "o.pdf", FakeBackend(), JobOptions(auto_glossary=False), ocr_backend=first)
    second = Vision()
    translate_book(scan, tmp_path / "o.pdf", FakeBackend(), JobOptions(auto_glossary=False), ocr_backend=second)
    assert len(second.read) == 2  # page 1 was read before the failure and is not read again


def test_scanned_pages_without_an_ocr_backend_are_still_written(tmp_path, scan):
    run(scan, tmp_path / "o.pdf")
    assert (tmp_path / "o.pdf").is_file()


def test_ocr_pages_can_be_written_in_another_format(tmp_path, scan):
    run(scan, tmp_path / "o.md", output_format="md", ocr_backend=None) if False else None
    vision = Vision()
    translate_book(scan, tmp_path / "o.md", FakeBackend(), JobOptions(auto_glossary=False, output_format="md"),
                   ocr_backend=vision)
    assert "Scanned text on page number 1" in (tmp_path / "o.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------- the recommendation

@pytest.mark.parametrize("total,language,expect", [
    (0, "", {"pages": False}), (1, "en", {"pages": False}), (40, "en", {"pages": False}), (41, "en", {"pages": True}),
    (-5, "en", {"pages": False}), (500, "en", {"pages": True, "review_names": True}),
    (500, "zh-CN", {"pages": True, "target": "en"}), (3, "klingon", {"source": False}),
    (3, None, {"source": False}), (500, "ja", {"pages": True, "review_names": False}),
])
def test_recommendation_for_odd_page_counts_and_languages(tmp_path, total, language, expect):
    d = fitz.open()
    d.new_page().insert_text((72, 100), "A page of text in a PDF file for the recommendation.")
    d.save(tmp_path / "a.pdf")
    got = recommend(tmp_path / "a.pdf", total, language)["settings"]
    for name, present in expect.items():
        if present is True or present is False:
            assert (name in got) is present, (name, got)
        else:
            assert got.get(name) == present, (name, got)
    assert got["output_mode"] == "bilingual" and set(recommend(tmp_path / "a.pdf", total, language)["reasons"]) == set(got)


def test_recommendation_for_a_scan_asks_for_ocr_and_for_a_text_book_does_not(tmp_path, scan):
    assert recommend(scan, 3, "")["settings"]["ocr"] is True
    d = fitz.open()
    for _ in range(3):
        d.new_page().insert_text((72, 100), "A page of text in a PDF file for the recommendation, long enough.")
    d.save(tmp_path / "text.pdf")
    assert recommend(tmp_path / "text.pdf", 3, "en")["settings"]["ocr"] is False


@pytest.mark.parametrize("name,fmt", [("a.docx", "docx"), ("a.md", "md"), ("a.markdown", "md"), ("a.epub", "epub"),
                                      ("a.txt", "epub")])
def test_recommended_output_format_by_input_kind(tmp_path, name, fmt):
    (tmp_path / name).write_bytes(b"x")  # looked at only by name: it need not be readable
    assert recommend(tmp_path / name, 3, "en")["settings"]["output_format"] == fmt


# ---------------------------------------------------------------- language detection on awkward text

@pytest.mark.parametrize("text", ["", "a", "OK", "1234 5678", "Hello", "你好", "こんにちは", "Привет", "مرحبا",
                                  "123 abc def", "e=mc^2", "https://example.com/a/b", "\x00\x01", "😀😀😀"])
def test_very_short_or_symbolic_text_is_unsure_not_wrong_and_never_an_error(text):
    got = languages.detect_language([text])
    assert got is None or got in languages.LANGUAGES


@pytest.mark.parametrize("text,code", [
    ("Dies ist ein langer deutscher Satz über das Wetter in Berlin, der sicher erkannt werden sollte. " * 3, "de"),
    ("Это длинное русское предложение о погоде в Москве, которое должно быть узнано без труда.", "ru"),
    ("これは東京の天気についての長い日本語の文章で、問題なく認識されるはずです。", "ja"),
    ("이것은 서울의 날씨에 대한 긴 한국어 문장이며 문제없이 인식되어야 합니다.", "ko"),
    ("هذه جملة عربية طويلة عن الطقس في القاهرة ويجب التعرف عليها بسهولة.", "ar"),
    ("这是一个关于北京天气的很长的中文句子，应该可以毫无困难地识别出来。", "zh-CN"),
])
def test_a_sentence_in_each_script_is_recognised(text, code):
    assert languages.detect_language([text]) == code


def test_a_book_in_two_languages_takes_the_main_one_and_a_foreign_cover_is_outvoted():
    pages = ["Le titre en français"] + ["This is an English page of a long book about gardens and weather in the north."] * 9
    assert languages.detect_language(pages) == "en"


# ---------------------------------------------------------------- audit round 3: reading order of a PDF written as text

def block(x0, y0, x1, y1):
    return {"bbox": (x0, y0, x1, y1)}


def test_reading_order_puts_a_title_drawn_last_first_and_a_left_column_before_a_right_one():
    from booktrans.pdfblocks import reading_order
    blocks = [block(40, 60, 290, 400), block(310, 60, 560, 400), block(40, 20, 300, 45)]  # left, right, title
    assert reading_order(blocks) == [2, 0, 1]


def test_reading_order_reads_a_column_to_its_end_before_the_next():
    from booktrans.pdfblocks import reading_order
    left = [block(40, 60, 290, 150), block(40, 160, 290, 300)]
    right = [block(310, 60, 560, 200), block(310, 210, 560, 300)]
    assert reading_order([right[1], left[1], right[0], left[0]]) == [3, 1, 2, 0]  # left 1, left 2, right 1, right 2


def test_reading_order_leaves_a_one_column_page_in_top_to_bottom_order_and_takes_odd_input():
    from booktrans.pdfblocks import reading_order
    page = [block(50, 100 * i, 500, 100 * i + 80) for i in range(6)]
    assert reading_order(page) == list(range(6))
    assert reading_order([]) == [] and reading_order([block(0, 0, 1, 1)]) == [0]
    assert sorted(reading_order([block(0, 0, 10, 10)] * 5)) == [0, 1, 2, 3, 4]  # blocks on top of each other


def test_a_two_column_pdf_with_its_title_drawn_last_is_written_in_reading_order(tmp_path):
    d = fitz.open()
    p = d.new_page()
    p.insert_textbox(fitz.Rect(40, 60, 290, 400), "LEFTCOLUMN text of the page. " * 8, fontsize=10)
    p.insert_textbox(fitz.Rect(310, 60, 560, 400), "RIGHTCOLUMN text of the page. " * 8, fontsize=10)
    p.insert_text((40, 40), "TITLEOFPAGE", fontsize=20)
    d.save(tmp_path / "two.pdf")
    run(tmp_path / "two.pdf", tmp_path / "o.md", output_format="md", output_mode="bilingual")
    text = (tmp_path / "o.md").read_text(encoding="utf-8")
    assert text.index("TITLEOFPAGE") < text.index("LEFTCOLUMN") < text.index("RIGHTCOLUMN")
