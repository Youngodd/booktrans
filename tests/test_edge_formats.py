"""Edge cases for reading any book as blocks and writing it in any format (docs/edge-case-test-plan.md,
areas 1 to 4): hostile and damaged files, odd text, odd structure, failing models, resume, page ranges."""
import re
from pathlib import Path
import zipfile

import fitz
import pytest

from booktrans import blocks as blocks_mod
from booktrans.backends.base import BackendError
from booktrans.blockreaders import read_blocks
from booktrans.blockwriters import write_blocks
from booktrans.options import JobOptions
from booktrans.pipeline import total_pages, translate_book
from booktrans.readers import UnreadableBook, read_book
from tests.conftest import FakeBackend

FORMATS = ("pdf", "epub", "docx", "md")


@pytest.fixture
def no_sleep(monkeypatch):
    from booktrans.backends import base
    monkeypatch.setattr(base.time, "sleep", lambda s: None)


def run(book, out, backend=None, **kw):
    kw.setdefault("auto_glossary", False)
    backend = backend or FakeBackend()
    translate_book(book, out, backend, JobOptions(**kw))
    return backend


def md(tmp_path, text, name="book.md"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def paragraphs(n, words=200):
    return "\n\n".join(f"Paragraph {i}. " + "word " * words for i in range(n)) + "\n"


# ---------------------------------------------------------------- 1. an uploaded book must not pull in other files

@pytest.fixture
def outside_file(tmp_path):
    (tmp_path / "secret.txt").write_text("TOPSECRET")
    (tmp_path / "secret.png").write_bytes(b"TOPSECRET-AS-PNG")
    folder = tmp_path / "upload"
    folder.mkdir()
    return tmp_path, folder


@pytest.mark.parametrize("src", ["../secret.png", "../secret.txt", "%2e%2e/secret.png", "..%2Fsecret.png",
                                 "sub/../../secret.png", "{abs}/secret.png", "file://{abs}/secret.png", "/etc/hosts",
                                 "\\\\host\\share\\x.png"])
def test_a_markdown_picture_outside_the_books_folder_is_not_read(outside_file, src):
    root, folder = outside_file
    book = md(folder, f"# T\n\n![x]({src.format(abs=root)})\n\nBody text.\n")
    found = read_blocks(book, root / "assets")
    assert not any(b["type"] == "figure" for b in found)
    assert not (root / "assets").exists() or not list((root / "assets").iterdir())


def test_a_markdown_picture_that_is_not_an_image_is_not_read(tmp_path):
    (tmp_path / "notes.txt").write_text("not a picture")
    (tmp_path / "x.png").write_bytes(b"\x89PNG-ish")
    found = read_blocks(md(tmp_path, "![a](notes.txt)\n\n![b](x.png)\n"), tmp_path / "assets")
    figures = [b for b in found if b["type"] == "figure"]
    assert [b["alt"] for b in figures] == ["b"]  # a picture next to the book, by its extension


def test_a_picture_next_to_the_book_with_a_space_or_percent_in_its_name_is_found(tmp_path):
    (tmp_path / "my pic.png").write_bytes(b"\x89PNG-ish")
    found = read_blocks(md(tmp_path, "![a](my%20pic.png)\n\n![b](<my pic.png>)\n"), tmp_path / "assets")
    assert [b["type"] for b in found] == ["figure", "figure"]


def test_a_web_picture_and_a_missing_picture_stay_as_text(tmp_path):
    found = read_blocks(md(tmp_path, "![a](https://example.com/a.png)\n\n![b](missing.png)\n"), tmp_path / "assets")
    assert [b["type"] for b in found] == ["para", "para"]
    assert "https://example.com/a.png" in found[0]["text"] and "missing.png" in found[1]["text"]


# ---------------------------------------------------------------- 2. damaged, empty and wrongly named files

@pytest.mark.parametrize("ext", [".docx", ".epub"])
@pytest.mark.parametrize("body", [b"", b"plain text, not a zip", b"PK\x03\x04truncated", b"\x00" * 64])
def test_a_damaged_word_or_epub_file_is_a_clear_error(tmp_path, ext, body):
    book = tmp_path / ("book" + ext)
    book.write_bytes(body)
    with pytest.raises(UnreadableBook) as e:
        read_blocks(book, tmp_path / "assets")
    assert ext in str(e.value) and "Traceback" not in str(e.value)
    assert isinstance(e.value, ValueError)  # what the callers already catch


def test_an_epub_saved_as_docx_and_a_docx_saved_as_epub_are_clear_errors(tmp_path):
    epub_like = tmp_path / "a.docx"
    with zipfile.ZipFile(epub_like, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
    with pytest.raises(UnreadableBook):
        read_blocks(epub_like, tmp_path / "assets")
    docx_like = tmp_path / "b.epub"
    with zipfile.ZipFile(docx_like, "w") as z:
        z.writestr("word/document.xml", "<w:document/>")
    with pytest.raises(UnreadableBook):
        read_blocks(docx_like, tmp_path / "assets")


@pytest.mark.parametrize("ext", [".md", ".txt", ".docx"])
def test_a_book_with_nothing_in_it_is_an_error_not_an_empty_file(tmp_path, ext):
    book = tmp_path / ("empty" + ext)
    if ext == ".docx":
        import docx
        docx.Document().save(str(book))
    else:
        book.write_text(" \n\n \t \n")
    with pytest.raises(ValueError, match="no pages"):
        translate_book(book, tmp_path / "o.md", FakeBackend(), JobOptions(output_format="md"))
    assert not (tmp_path / "o.md").exists()


def test_a_book_of_pictures_only_has_nothing_to_translate(tmp_path):
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 20, 20), False)
    pix.set_rect(pix.irect, (200, 30, 30))
    pix.save(str(tmp_path / "p.png"))
    book = md(tmp_path, "![only a picture](p.png)\n")
    assert [b["type"] for b in read_blocks(book, tmp_path / "assets")] == ["figure"]
    with pytest.raises(ValueError, match="no pages"):
        translate_book(book, tmp_path / "o.docx", FakeBackend(), JobOptions(output_format="docx"))


def make_pdf(path, **save):
    d = fitz.open()
    for i in range(2):
        d.new_page().insert_text((72, 100), f"Book text number {i} " * 6)
    d.save(path, **save)
    return path


def test_a_pdf_that_needs_a_password_says_so(tmp_path):
    book = make_pdf(tmp_path / "locked.pdf", encryption=fitz.PDF_ENCRYPT_RC4_128, owner_pw="o", user_pw="u")
    for call in (lambda: read_book(book), lambda: total_pages(book),
                 lambda: translate_book(book, tmp_path / "o.pdf", FakeBackend(), JobOptions())):
        with pytest.raises(UnreadableBook, match="password"):
            call()


def test_a_pdf_locked_only_against_copying_opens_with_the_empty_password(tmp_path):
    book = make_pdf(tmp_path / "owner.pdf", encryption=fitz.PDF_ENCRYPT_RC4_128, owner_pw="o", user_pw="")
    assert total_pages(book) == 2
    assert "Book text number 1" in read_book(book)[1]


def test_an_aes_encrypted_pdf_without_the_cryptography_package_says_what_to_install(tmp_path):
    try:
        import cryptography  # noqa: F401
    except ImportError:
        pass
    else:
        pytest.skip("the cryptography package is installed: AES PDFs open")
    book = make_pdf(tmp_path / "aes.pdf", encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="")
    with pytest.raises(UnreadableBook, match="cryptography"):
        read_book(book)


def test_recommendation_survives_a_locked_or_broken_pdf(tmp_path):
    from booktrans.recommend import recommend
    locked = make_pdf(tmp_path / "locked.pdf", encryption=fitz.PDF_ENCRYPT_RC4_128, owner_pw="o", user_pw="u")
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.4 truncated")
    for book in (locked, broken, tmp_path / "missing.pdf"):
        got = recommend(book, 0, "")
        assert got["settings"]["output_mode"] == "bilingual"


# ---------------------------------------------------------------- 2. text files: one paragraph per line, huge paragraphs

def test_a_text_with_one_paragraph_per_line_keeps_its_paragraphs(tmp_path):
    lines = [f"Line {i} of the story, a short paragraph." for i in range(50)]
    book = tmp_path / "story.txt"
    book.write_text("\n".join(lines))
    found = read_blocks(book, tmp_path / "assets")
    assert [b["text"] for b in found] == lines


def test_chinese_paragraphs_on_single_lines_are_neither_merged_nor_given_spaces(tmp_path):
    para = "他走进了房间，看见桌上放着一封信。" * 3
    book = tmp_path / "novel.txt"
    book.write_text("\n".join("　　" + para for _ in range(300)), encoding="utf-8")
    found = read_blocks(book, tmp_path / "assets")
    assert len(found) == 300 and all(b["text"] == para for b in found)
    assert len(blocks_mod.units(found)) > 1  # not one request for the whole book


def test_lines_wrapped_inside_a_paragraph_are_joined_and_blank_lines_still_separate(tmp_path):
    book = tmp_path / "wrapped.txt"
    book.write_text("first line of one\nsecond line of one\n\nanother paragraph\n")
    assert [b["text"] for b in read_blocks(book, tmp_path / "assets")] == [
        "first line of one second line of one", "another paragraph"]


def test_chinese_lines_wrapped_inside_a_paragraph_are_joined_without_a_space(tmp_path):
    book = tmp_path / "wrapped.txt"
    book.write_text("第一行文字\n第二行文字\n\n第二段\n", encoding="utf-8")
    assert [b["text"] for b in read_blocks(book, tmp_path / "assets")] == ["第一行文字第二行文字", "第二段"]


@pytest.mark.parametrize("name", ["huge.txt", "huge.md"])
def test_one_enormous_paragraph_is_cut_into_pages_and_loses_no_word(tmp_path, name):
    words = [f"w{i}" for i in range(40000)]
    book = tmp_path / name
    book.write_text(" ".join(words))
    found = read_blocks(book, tmp_path / "assets")
    assert len(found) > 50 and max(len(b["text"]) for b in found) <= 1800
    assert " ".join(b["text"] for b in found).split() == words
    sent = run(book, tmp_path / "o.md", output_format="md")
    assert len(sent.calls) == len(blocks_mod.units(found)) and max(len(c) for c in sent.calls) < 6000


def test_a_long_book_is_cut_into_requests_of_a_page(tmp_path):
    book = md(tmp_path, paragraphs(300, words=40))
    sent = run(book, tmp_path / "o.md", output_format="md")
    assert len(sent.calls) > 5 and max(len(c) for c in sent.calls) < 6000
    assert (tmp_path / "o.md").read_text().count("Paragraph ") == 300


# ---------------------------------------------------------------- 2. markdown and Word structure

def test_markdown_edge_structure(tmp_path):
    book = md(tmp_path, "---\n\n# H\r\n\r\n```py\r\ncode never closed\r\n")  # CRLF, a rule, an unclosed fence
    found = read_blocks(book, tmp_path / "a")
    assert [b["type"] for b in found] == ["heading", "code"] and found[1]["text"] == "code never closed"


def test_markdown_with_old_mac_line_endings(tmp_path):
    p = tmp_path / "cr.md"
    p.write_bytes(b"# H\rpara one\rpara two\r")
    assert [(b["type"], b["text"]) for b in read_blocks(p, tmp_path / "a")] == [
        ("heading", "H"), ("para", "para one para two")]


def test_a_markdown_table_with_ragged_rows_is_made_even(tmp_path):
    book = md(tmp_path, "| a | b |\n|---|---|\n| 1 |\n| 1 | 2 | 3 |\n| x \\| y | z |\n")
    (table,) = read_blocks(book, tmp_path / "a")
    assert len({len(r) for r in table["rows"]}) == 1 and table["rows"][-1][:2] == ["x | y", "z"]


def test_markdown_with_a_byte_order_mark_and_a_legacy_encoding(tmp_path):
    p = tmp_path / "bom.md"
    p.write_bytes(b"\xef\xbb\xbf# Title\n\nBody\n")
    assert read_blocks(p, tmp_path / "a")[0]["text"] == "Title"
    g = tmp_path / "gbk.md"
    g.write_bytes("# 标题\n\n这是正文，用国标码保存的文件。\n".encode("gbk"))
    assert read_blocks(g, tmp_path / "a")[0]["text"] == "标题"


def test_a_word_table_with_merged_and_empty_cells_and_a_nested_table_keeps_all_its_text(tmp_path):
    import docx
    d = docx.Document()
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).merge(t.cell(0, 1)).text = "merged heading"
    t.cell(1, 0).text = ""
    inner = t.cell(1, 1).add_table(rows=1, cols=2)
    inner.cell(0, 0).text = "inner one"
    inner.cell(0, 1).text = "inner two"
    d.save(str(tmp_path / "t.docx"))
    (table,) = read_blocks(tmp_path / "t.docx", tmp_path / "a")
    text = " | ".join(c for r in table["rows"] for c in r)
    assert "merged heading" in text and "inner one" in text and "inner two" in text


def test_a_word_file_with_only_a_table_is_translated_cell_by_cell(tmp_path):
    import docx
    d = docx.Document()
    t = d.add_table(rows=2, cols=2)
    for i, c in enumerate(t._cells):
        c.text = f"cell {i}"
    d.save(str(tmp_path / "t.docx"))
    run(tmp_path / "t.docx", tmp_path / "o.md", output_format="md")
    out = (tmp_path / "o.md").read_text()
    assert all(f"cell {i}" in out for i in range(4)) and out.count("译") == 4


# ---------------------------------------------------------------- 3. writers: hostile text, odd structure, missing files

NASTY = ['x & y < z > "q" \'s\'', "control\x00\x01\x07chars\x0b\x0c here", "bad � char", "emoji \U0001F600\U0001F389 text",
         "مرحبا بالعالم", "a" * 5000, "नमस्ते दुनिया", "line1\nline2\r\nline3", "‮RLO override‬",
         "</p><script>alert(1)</script>", "日本語のテキスト", "한국어 텍스트"]


def nasty_blocks():
    blocks = [{"type": "heading", "text": "Title & <b>", "level": 1, "tr": "标题 & <b>"}]
    blocks += [{"type": "para", "text": t, "tr": "译:" + t} for t in NASTY]
    blocks += [{"type": "table", "rows": [["a"], ["b", "c", "d"], []], "tr_rows": [["甲"], ["乙", "丙", "丁"], []]},
               {"type": "table", "rows": [["only"]]},
               {"type": "list", "text": "item", "level": 7, "ordered": True, "tr": "项"},
               {"type": "code", "text": "x = '<&>'"},
               {"type": "break"},
               {"type": "para", "text": "kept as it is", "tr": "~"},
               {"type": "para", "text": "no translation", "tr": ""}]
    return blocks


def written_text(path):
    """All the text of an output file, whatever its format."""
    ext = path.suffix
    if ext == ".pdf":
        with fitz.open(str(path)) as d:
            return "\n".join(p.get_text() for p in d)
    if ext == ".md":
        return path.read_text(encoding="utf-8")
    if ext == ".docx":
        import docx
        d = docx.Document(str(path))
        return "\n".join([p.text for p in d.paragraphs] + [c.text for t in d.tables for r in t.rows for c in r.cells])
    with zipfile.ZipFile(path) as z:
        return "\n".join(z.read(n).decode("utf-8") for n in z.namelist() if n.endswith((".xhtml", ".html")))


@pytest.mark.parametrize("fmt", FORMATS)
@pytest.mark.parametrize("bilingual", [True, False])
def test_every_writer_takes_hostile_text_and_writes_a_file_that_opens(tmp_path, fmt, bilingual):
    out = tmp_path / f"o.{fmt}"
    write_blocks(nasty_blocks(), tmp_path / "assets", out, fmt, bilingual=bilingual, lang="zh-CN", title="T & <x>")
    text = written_text(out)
    assert "kept as it is" in text and "~" not in text.replace("~~", "")  # "keep" is never shown as a tilde
    assert text.count("kept as it is") == 1 if fmt != "epub" else True
    if fmt in ("docx", "epub", "md"):
        assert "\x00" not in text and "\x07" not in text


@pytest.mark.parametrize("fmt", ["docx", "epub", "md"])
def test_text_is_escaped_not_interpreted(tmp_path, fmt):
    out = tmp_path / f"o.{fmt}"
    write_blocks([{"type": "para", "text": "</p><script>alert(1)</script>", "tr": "<img src=x onerror=alert(1)>"}],
                 tmp_path / "assets", out, fmt, bilingual=True, lang="zh-CN", title="T")
    if fmt == "epub":
        html = written_text(out)
        assert "<script>" not in html and "<img src=x" not in html


@pytest.mark.parametrize("fmt", FORMATS)
def test_writing_no_blocks_gives_a_file_that_opens(tmp_path, fmt):
    out = tmp_path / f"o.{fmt}"
    write_blocks([], tmp_path / "assets", out, fmt, bilingual=True, lang="zh-CN", title="T")
    assert out.is_file() and out.stat().st_size > 0


@pytest.mark.parametrize("fmt", FORMATS)
def test_a_right_to_left_target_is_written_in_every_format(tmp_path, fmt):
    out = tmp_path / f"o.{fmt}"
    blocks = [{"type": "heading", "text": "Title", "level": 1, "tr": "عنوان الكتاب"},
              {"type": "para", "text": "Body", "tr": "نص الفقرة الأولى من الكتاب"}]
    for bilingual in (True, False):
        write_blocks([dict(b) for b in blocks], tmp_path / "assets", out, fmt, bilingual=bilingual, lang="ar", title="T")
        assert out.is_file()
    if fmt != "pdf":
        assert "عنوان الكتاب" in written_text(out)


@pytest.mark.parametrize("fmt", FORMATS)
def test_a_picture_whose_file_is_gone_is_left_out_not_a_crash(tmp_path, fmt):
    out = tmp_path / f"o.{fmt}"
    blocks = [{"type": "para", "text": "before", "tr": "前"},
              {"type": "figure", "image": "gone.png", "alt": 'al"t<'},
              {"type": "para", "text": "after", "tr": "后"}]
    write_blocks(blocks, tmp_path / "assets", out, fmt, bilingual=True, lang="zh-CN", title="T")
    text = written_text(out)
    assert "before" in text and "after" in text


@pytest.mark.parametrize("fmt", ["md", "docx", "epub", "pdf"])
def test_the_output_folder_is_made_when_it_does_not_exist(tmp_path, fmt):
    book = md(tmp_path, "# T\n\nSome text to translate.\n")
    out = tmp_path / "new" / "deeper" / f"o.{fmt}"
    run(book, out, output_format=fmt)
    assert out.is_file()


def test_a_pdf_book_also_gets_its_output_folder(text_pdf, tmp_path):
    out = tmp_path / "made" / "o.pdf"
    run(text_pdf, out)
    assert out.is_file()


@pytest.mark.parametrize("name", ["我的书 第1章.md", "book with  spaces.md", "x" * 120 + ".md", "émile & co.md", "a.b.c.md"])
def test_odd_file_names_work_through_every_step(tmp_path, name):
    book = md(tmp_path, "# T\n\nSome text to translate.\n", name=name)
    out = tmp_path / ("译 " + name).replace(".md", ".docx")
    run(book, out, output_format="docx")
    assert out.is_file() and "译" in written_text(out)


# ---------------------------------------------------------------- 4. page ranges, models that fail, cache and resume

@pytest.mark.parametrize("spec,message", [("0", "outside"), ("99", "outside"), ("0-0", "outside"), ("5-", "Invalid"),
                                          ("a-b", "Invalid"), ("-3", "Invalid"), ("9-2", "before start"),
                                          ("1.5", "Invalid"), (" ", None), ("3-3-3", "Invalid")])
def test_a_senseless_page_range_is_refused_before_anything_is_paid_for(tmp_path, spec, message):
    book = md(tmp_path, paragraphs(12))
    backend = FakeBackend()
    if message is None:
        translate_book(book, tmp_path / "o.md", backend, JobOptions(pages=spec, output_format="md", auto_glossary=False))
        return
    with pytest.raises(ValueError, match=message):
        translate_book(book, tmp_path / "o.md", backend, JobOptions(pages=spec, output_format="md", auto_glossary=False))
    assert backend.calls == []


def test_a_range_running_past_the_end_is_clamped_and_one_part_is_enough(tmp_path):
    book = md(tmp_path, paragraphs(12))
    all_parts = len(blocks_mod.units(read_blocks(book, tmp_path / "a")))
    assert len(run(book, tmp_path / "o.md", output_format="md", pages=f"1-{all_parts + 50}").calls) == all_parts
    one = run(book, tmp_path / "one.md", output_format="md", pages="2")
    assert len(one.calls) == 1
    text = (tmp_path / "one.md").read_text()
    assert "译" in text and text.count("Paragraph ") < 12  # only that part, not the whole book


def test_redo_outside_the_book_is_ignored_and_a_valid_redo_pays_for_those_parts_only(tmp_path):
    book = md(tmp_path, paragraphs(12))
    run(book, tmp_path / "o.md", output_format="md")
    assert run(book, tmp_path / "o.md", output_format="md", redo="99").calls == []
    assert len(run(book, tmp_path / "o.md", output_format="md", redo="1").calls) == 1


def test_a_part_that_keeps_failing_stops_the_book_and_the_next_run_pays_only_for_the_rest(tmp_path, no_sleep):
    book = md(tmp_path, paragraphs(12))
    parts = len(blocks_mod.units(read_blocks(book, tmp_path / "a")))
    assert parts >= 3

    class Breaks(FakeBackend):
        def complete(self, system, user, max_tokens=4096):
            if "Paragraph 8." in user:
                raise BackendError("the connection dropped")
            return super().complete(system, user, max_tokens)

    first = Breaks()
    with pytest.raises(BackendError):
        translate_book(book, tmp_path / "o.md", first, JobOptions(output_format="md", auto_glossary=False))
    assert not (tmp_path / "o.md").exists()  # no half-written book
    second = FakeBackend()
    run(book, tmp_path / "o.md", second, output_format="md")
    assert 1 <= len(second.calls) < parts  # the parts done before the failure are not paid for again
    assert (tmp_path / "o.md").read_text().count("译") >= 12


def test_a_model_that_answers_keep_for_everything_leaves_the_book_as_it_was(tmp_path):
    book = md(tmp_path, paragraphs(4, words=20))

    def keep(user):
        return "\n".join(f"[{n}] ~" for n in re.findall(r"(?m)^\[(\d+)\]", user))
    run(book, tmp_path / "o.md", FakeBackend(reply=keep), output_format="md", output_mode="bilingual")
    text = (tmp_path / "o.md").read_text()
    assert text.count("Paragraph 0.") == 1 and "~" not in text  # the original once, no tilde, no duplicate


@pytest.mark.parametrize("reply", ["", "   \n ", "\n\n"])
def test_a_model_that_answers_nothing_never_erases_the_book(tmp_path, no_sleep, reply):
    book = md(tmp_path, paragraphs(3, words=20))
    run(book, tmp_path / "o.md", FakeBackend(reply=reply), output_format="md", output_mode="target-only")
    text = (tmp_path / "o.md").read_text()
    assert all(f"Paragraph {i}." in text for i in range(3))  # the originals stay where the translations were missing


@pytest.mark.parametrize("reply", ["no markers at all", "[1] only the first\n[7] a stray number", "[0] zero", "[2] [1] swapped"])
def test_a_model_that_ignores_the_numbering_still_gives_a_book_with_every_passage(tmp_path, no_sleep, reply):
    book = md(tmp_path, paragraphs(3, words=20))
    run(book, tmp_path / "o.md", FakeBackend(reply=reply), output_format="md", output_mode="bilingual")
    text = (tmp_path / "o.md").read_text()
    assert all(f"Paragraph {i}." in text for i in range(3))  # bilingual: the originals are there whatever it said


BAD_CACHES = ["[]", "null", '"text"', "5", "{", '{"B0": 5}', '{"B0": {"x": 1}}', '{"B0": []}', '{"B0": {"src": 1, "tr": 2}}',
              '{"B0": {"src": ["a"], "tr": []}}', '\x00\x01', ""]


@pytest.mark.parametrize("body", BAD_CACHES)
def test_a_damaged_cache_is_ignored_and_the_book_still_comes_out(tmp_path, body):
    book = md(tmp_path, paragraphs(3, words=20))
    (tmp_path / "o.cache.json").write_text(body)
    run(book, tmp_path / "o.md", output_format="md")
    assert (tmp_path / "o.md").read_text().count("译") >= 3


def test_a_damaged_glossary_or_spend_file_does_not_stop_a_book(tmp_path):
    book = md(tmp_path, paragraphs(3, words=20))
    for suffix in (".glossary.json", ".used.json", ".spend.json"):
        (tmp_path / ("o" + suffix)).write_text("{not json")
    run(book, tmp_path / "o.md", output_format="md", auto_glossary=True)
    assert (tmp_path / "o.md").is_file()


def test_switching_the_target_language_does_not_reuse_the_other_languages_parts(tmp_path):
    book = md(tmp_path, paragraphs(3, words=20))
    run(book, tmp_path / "o.md", output_format="md", target="zh-CN")
    french = run(book, tmp_path / "o.md", output_format="md", target="fr")
    assert french.calls  # not served from the Chinese cache


def test_switching_between_bilingual_and_target_only_pays_nothing(tmp_path):
    book = md(tmp_path, paragraphs(3, words=20))
    run(book, tmp_path / "o.md", output_format="md", output_mode="bilingual")
    again = run(book, tmp_path / "t.md", output_format="md", output_mode="target-only", state=tmp_path / "o.md")
    assert again.calls == []
    text = (tmp_path / "t.md").read_text()
    assert "Paragraph 0." not in text and "译" in text


def test_finishing_without_spending_when_nothing_was_translated_is_an_error(tmp_path):
    book = md(tmp_path, paragraphs(3, words=20))
    with pytest.raises(ValueError, match="Nothing has been translated"):
        translate_book(book, tmp_path / "o.md", FakeBackend(), JobOptions(output_format="md", only_cached=True))


def test_finishing_without_spending_after_a_partial_run_writes_the_translated_part(tmp_path):
    book = md(tmp_path, paragraphs(12))
    run(book, tmp_path / "o.md", output_format="md", pages="1")
    backend = FakeBackend()
    translate_book(book, tmp_path / "done.md", backend, JobOptions(output_format="md", only_cached=True, state=tmp_path / "o.md"))
    assert backend.calls == [] and (tmp_path / "done.md").read_text().count("译") >= 1


def test_the_same_language_as_source_and_target_still_runs(tmp_path):
    book = md(tmp_path, "# T\n\nSome text in English to translate.\n")
    run(book, tmp_path / "o.md", output_format="md", source="en", target="en")
    assert "Some text in English" in (tmp_path / "o.md").read_text()


def test_a_refresh_of_the_glossary_with_no_glossary_pays_for_nothing(tmp_path):
    book = md(tmp_path, paragraphs(3, words=20))
    run(book, tmp_path / "o.md", output_format="md")
    assert run(book, tmp_path / "o.md", output_format="md", refresh_glossary=True, auto_glossary=False).calls == []


def test_the_spend_limit_stops_a_block_book_and_the_parts_paid_for_are_kept(tmp_path):
    from booktrans import spend
    from booktrans.pipeline import SpendLimitReached
    from tests.conftest import PricedBackend
    book = md(tmp_path, paragraphs(12))
    parts = len(blocks_mod.units(read_blocks(book, tmp_path / "a")))
    meter = spend.Meter(1.5)  # the fake prices make every call cost ¥1
    with pytest.raises(SpendLimitReached):
        translate_book(book, tmp_path / "o.md", PricedBackend(), JobOptions(output_format="md", auto_glossary=False), meter=meter)
    resumed = run(book, tmp_path / "o.md", output_format="md")
    assert 0 < len(resumed.calls) < parts


def test_two_runs_at_once_on_the_same_cache_do_not_corrupt_it(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    book = md(tmp_path, paragraphs(8))
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(run, book, tmp_path / f"o{i}.md", output_format="md", state=tmp_path / "shared.md")
                   for i in range(2)]
        for f in futures:
            f.result()
    from booktrans.fsutil import read_json
    cache = read_json(tmp_path / "shared.cache.json")
    assert cache and all(isinstance(v, dict) and len(v["src"]) == len(v["tr"]) for v in cache.values())


# ---------------------------------------------------------------- audit round 1

def test_a_wrapped_single_paragraph_with_no_blank_lines_stays_one_paragraph(tmp_path):
    book = tmp_path / "email.txt"
    book.write_text("This is one long paragraph that has been wrapped by an editor so that no line is\n"
                    "longer than seventy-two characters, which means that most of its lines stop in the\n"
                    "middle of a sentence and must be joined back into the paragraph they came from.\n")
    found = read_blocks(book, tmp_path / "assets")
    assert len(found) == 1 and "joined back" in found[0]["text"] and "\n" not in found[0]["text"]


def test_lines_that_each_end_a_sentence_are_separate_paragraphs(tmp_path):
    book = tmp_path / "lines.txt"
    book.write_text("First thing happened.\nSecond thing happened!\nWas there a third?\n他回家了。\n")
    assert len(read_blocks(book, tmp_path / "assets")) == 4


def test_an_epub_with_a_very_long_paragraph_is_still_written_back_into_the_book_itself(tmp_path):
    import zipfile
    from tests.test_edge_more import make_epub
    long_p = "Sentence number one is here. " * 160
    book = make_epub(tmp_path / "t.epub", [f"<html><head><style>p{{color:red}}</style></head><body><h1>T</h1>"
                                           f"<p>{long_p}</p><p>Short one.</p></body></html>"])
    run(book, tmp_path / "o.epub", output_format="epub")
    with zipfile.ZipFile(tmp_path / "o.epub") as z:
        names = z.namelist()
        html = z.read(next(n for n in names if n.endswith("c0.xhtml"))).decode()
    assert "bt-tr" in html  # the book's own chapter file with the translation put in, not a newly made EPUB


def test_the_log_location_survives_a_missing_home_folder(monkeypatch):
    from booktrans import failure
    monkeypatch.delenv("BOOKTRANS_LOG")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: (_ for _ in ()).throw(RuntimeError("no home"))))
    assert failure.log_path().name == "error.log"


# ---------------------------------------------------------------- audit round 3: text that looks like Markdown

@pytest.mark.parametrize("text", ["1984. was a novel by Orwell", "2) a numbered thing", "# not a heading", "## also not",
                                  "- not a list", "+ plus", "* star", "> not a quote", "```not a fence", "~~~ nor this",
                                  "---", "***", "===", "line one\n# line two", "   1. indented"])
def test_a_paragraph_that_looks_like_markdown_stays_a_paragraph(tmp_path, text):
    out = tmp_path / "o.md"
    write_blocks([{"type": "para", "text": text, "tr": "译:" + text}], tmp_path / "a", out, "md", bilingual=True, lang="zh-CN")
    back = read_blocks(out, tmp_path / "b")
    assert [b["type"] for b in back] == ["para", "para"], (text, out.read_text())


def test_ordinary_paragraphs_are_not_changed_by_the_escaping():
    from booktrans.blockwriters import md_paragraph
    for text in ["Plain sentence.", "A #hashtag and a - dash and 3.5 apples", "He said > 5", "snake_case_name", "2 * 3"]:
        assert md_paragraph(text) == text
