"""Word, Markdown and EPUB in and out: text, pictures and tables carry over in order, and a
second output format is built from the cache without a model call."""
import zipfile

import fitz
import pytest

from booktrans.blockreaders import read_blocks
from booktrans.blocks import segments, units
from booktrans.options import JobOptions
from booktrans.pipeline import reads_as_blocks, total_pages, translate_book
from tests.conftest import FakeBackend

FORMATS = ("pdf", "epub", "docx", "md")


def png(path, color=(200, 30, 30)):
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 120, 80))
    pix.set_rect(pix.irect, color)
    pix.save(str(path))
    return path


@pytest.fixture
def md_book(tmp_path):
    png(tmp_path / "pic.png")
    p = tmp_path / "book.md"
    p.write_text("# The Title\n\nFirst paragraph with **bold** text\nwrapped on two lines.\n\n"
                 "![a red box](pic.png)\n\n"
                 "| Name | Value |\n| --- | --- |\n| alpha | one |\n| beta | two |\n\n"
                 "- first item\n- second item\n\n```\ncode stays = as_is\n```\n\n## Second\n\nLast paragraph.\n",
                 encoding="utf-8")
    return p


@pytest.fixture
def docx_book(tmp_path):
    import docx
    d = docx.Document()
    d.add_heading("The Title", level=1)
    d.add_paragraph("First paragraph of the Word book.")
    d.add_picture(str(png(tmp_path / "pic.png")))
    t = d.add_table(rows=2, cols=2)
    for r, row in enumerate((("Name", "Value"), ("alpha", "one"))):
        for c, text in enumerate(row):
            t.cell(r, c).text = text
    d.add_paragraph("first item", style="List Bullet")
    d.add_paragraph("Last paragraph.")
    d.save(str(tmp_path / "book.docx"))
    return tmp_path / "book.docx"


@pytest.fixture
def epub_book(tmp_path):
    from ebooklib import epub
    book = epub.EpubBook()
    book.set_identifier("id")
    book.set_title("T")
    book.set_language("en")
    book.add_item(epub.EpubItem(uid="css", file_name="style/own.css", media_type="text/css", content="p {color: green;}"))
    book.add_item(epub.EpubItem(uid="pic", file_name="images/pic.png", media_type="image/png",
                                content=png(tmp_path / "pic.png").read_bytes()))
    chapters = []
    for n in (1, 2):
        c = epub.EpubHtml(title=f"C{n}", file_name=f"c{n}.xhtml")
        c.content = (f'<h1>Chapter {n}</h1><p class="own">A paragraph of chapter {n}.</p>'
                     '<p><img src="images/pic.png" alt="pic"/></p>'
                     "<table><tr><td>Name</td><td>Value</td></tr><tr><td>alpha</td><td>one</td></tr></table>"
                     "<ul><li>first item</li></ul>")
        book.add_item(c)
        chapters.append(c)
    book.toc = chapters
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav"] + chapters
    epub.write_epub(str(tmp_path / "book.epub"), book)
    return tmp_path / "book.epub"


def kinds(blocks):
    return [b["type"] for b in blocks if b["type"] != "break"]


def read_back(path, tmp_path):
    """The blocks of an output file (a PDF is read as its text and picture count)."""
    if path.suffix == ".pdf":
        with fitz.open(str(path)) as d:
            return {"text": "\n".join(p.get_text() for p in d), "images": sum(len(p.get_images()) for p in d)}
    return read_blocks(path, tmp_path / ("back_" + path.suffix[1:]))


def test_markdown_is_read_as_blocks_with_its_picture_and_table(md_book, tmp_path):
    blocks = read_blocks(md_book, tmp_path / "a")
    assert kinds(blocks) == ["heading", "para", "figure", "table", "list", "list", "code", "heading", "para"]
    assert blocks[1]["text"] == "First paragraph with **bold** text wrapped on two lines."
    assert blocks[3]["rows"] == [["Name", "Value"], ["alpha", "one"], ["beta", "two"]]
    assert (tmp_path / "a" / blocks[2]["image"]).is_file()
    assert all("code stays" not in text for _, _, text in segments(blocks))  # code is not translated


def test_word_is_read_as_blocks_with_its_picture_and_table(docx_book, tmp_path):
    blocks = read_blocks(docx_book, tmp_path / "a")
    assert kinds(blocks) == ["heading", "para", "figure", "table", "list", "para"]
    assert blocks[3]["rows"] == [["Name", "Value"], ["alpha", "one"]]


def test_epub_is_read_as_blocks_chapter_by_chapter(epub_book, tmp_path):
    blocks = read_blocks(epub_book, tmp_path / "a")
    assert [b["type"] for b in blocks].count("break") == 1
    assert kinds(blocks)[:5] == ["heading", "para", "figure", "table", "list"]


@pytest.mark.parametrize("source", ["md_book", "docx_book", "epub_book"])
@pytest.mark.parametrize("fmt", FORMATS)
@pytest.mark.parametrize("mode", ["bilingual", "target-only"])
def test_every_pair_carries_text_picture_and_table(source, fmt, mode, request, tmp_path):
    book = request.getfixturevalue(source)
    if not reads_as_blocks(book, fmt):
        pytest.skip("EPUB to PDF is the plain-text path, tested elsewhere")
    out = tmp_path / f"out.{fmt}"
    translate_book(book, out, FakeBackend(), JobOptions(output_format=fmt, output_mode=mode, auto_glossary=False))
    got = read_back(out, tmp_path)
    if fmt == "pdf":
        assert got["images"] >= 1 and "译" in got["text"]
        assert ("The Title" in got["text"] or "Chapter 1" in got["text"]) == (mode == "bilingual")
        return
    types = kinds(got)
    assert "figure" in types and "table" in types and "heading" in types
    table = next(b for b in got if b["type"] == "table")
    flat = " ".join(c for row in table["rows"] for c in row)
    assert "译" in flat and ("alpha" in flat) == (mode == "bilingual")
    texts = " ".join(b.get("text", "") for b in got)
    assert "译" in texts and ("paragraph" in texts) == (mode == "bilingual")


def test_a_second_format_is_built_from_the_cache_without_a_call(md_book, tmp_path):
    state = tmp_path / "state.pdf"
    first = FakeBackend()
    translate_book(md_book, tmp_path / "o.epub", first, JobOptions(output_format="epub", state=state, auto_glossary=False))
    assert first.calls
    for fmt in ("docx", "md", "pdf", "epub"):
        again = FakeBackend()
        translate_book(md_book, tmp_path / f"o2.{fmt}", again,
                       JobOptions(output_format=fmt, state=state, auto_glossary=False))
        assert again.calls == []
    only = FakeBackend()
    translate_book(md_book, tmp_path / "o3.md", only, JobOptions(output_format="md", state=state, only_cached=True))
    assert only.calls == []


def test_changed_text_is_translated_again_and_the_rest_is_not(md_book, tmp_path):
    opts = JobOptions(output_format="md", auto_glossary=False)
    translate_book(md_book, tmp_path / "o.md", FakeBackend(), opts)
    md_book.write_text(md_book.read_text(encoding="utf-8") + "\n" + "A new closing paragraph. " * 120 + "\n",
                       encoding="utf-8")
    assert total_pages(md_book) == 2
    again = FakeBackend()
    translate_book(md_book, tmp_path / "o.md", again, opts)
    assert len(again.calls) == 1 and "new closing paragraph" in again.calls[0]


def test_an_epub_written_as_epub_keeps_its_own_files(epub_book, tmp_path):
    out = tmp_path / "o.epub"
    translate_book(epub_book, out, FakeBackend(), JobOptions(output_format="epub", auto_glossary=False))
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        assert names[0] == "mimetype"
        assert any(n.endswith("style/own.css") for n in names) and any(n.endswith("images/pic.png") for n in names)
        chapter = z.read(next(n for n in names if n.endswith("c1.xhtml"))).decode("utf-8")
    assert 'class="own"' in chapter and "bt-tr" in chapter and "A paragraph of chapter 1." in chapter


def test_a_pdf_written_as_markdown_has_its_text_in_order_and_its_picture(tmp_path):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 90), "A Big Heading", fontsize=24)
    page.insert_textbox(fitz.Rect(72, 120, 500, 200), "This is a body paragraph of the book that is long "
                        "enough to wrap across several lines on the page, and then some more.", fontsize=11)
    page.insert_image(fitz.Rect(72, 220, 272, 340), filename=str(png(tmp_path / "pic.png")))
    page.insert_textbox(fitz.Rect(72, 360, 500, 420), "A second paragraph that comes after the picture "
                        "and is also long enough to be body text.", fontsize=11)
    doc.save(str(tmp_path / "b.pdf"))
    out = tmp_path / "o.md"
    backend = FakeBackend()
    translate_book(tmp_path / "b.pdf", out, backend, JobOptions(output_format="md", auto_glossary=False))
    blocks = read_blocks(out, tmp_path / "back")
    assert kinds(blocks)[0] == "heading" and blocks[0]["text"] == "A Big Heading"
    where = kinds(blocks).index("figure")
    assert 0 < where < len(blocks) - 1  # between the two paragraphs
    again = FakeBackend()  # the PDF's own cache serves the PDF output too
    translate_book(tmp_path / "b.pdf", tmp_path / "o.pdf", again, JobOptions(state=out, auto_glossary=False))
    assert again.calls == []


def test_units_do_not_cut_a_small_table(tmp_path):
    blocks = [{"type": "para", "text": "x" * 1700},
              {"type": "table", "rows": [["a" * 60, "b" * 60], ["c" * 60, "d" * 60]]}]
    cut = [u for u in units(blocks) if any(k == 1 for k, _, _ in u)]
    assert len(cut) == 1 and sum(1 for k, _, _ in cut[0] if k == 1) == 4  # all four cells together


def test_an_unknown_output_format_is_refused():
    with pytest.raises(ValueError):
        JobOptions(output_format="mobi")


# ---------------------------------------------------------------- the web service

@pytest.fixture
def client(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from fastapi.testclient import TestClient
    from booktrans.web.app import create_app
    pool = ThreadPoolExecutor(max_workers=1)
    yield TestClient(create_app(tmp_path / "data", executor=pool,
                                backend_factory=lambda key, provider="api", **kw: FakeBackend()))
    pool.shutdown(wait=True)


def finished(client, job_id):
    import time
    end = time.time() + 20
    while time.time() < end:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["state"] in ("done", "failed"):
            return j
        time.sleep(0.05)
    raise AssertionError("job did not finish")


KEY = "sk-ant-test-1234567890abcdefghij"


def test_an_upload_comes_back_with_suggested_settings(client, md_book):
    j = client.post("/api/jobs", files={"file": ("book.md", md_book.read_bytes())}).json()
    rec = j["recommended"]
    assert rec["settings"]["output_format"] == "md" and rec["settings"]["output_mode"] == "bilingual"
    assert set(rec["reasons"]) == set(rec["settings"]) and rec["reasons"]["output_format"]["zh"]
    assert client.post("/api/jobs", files={"file": ("book.mobi", b"x")}).status_code == 400


def test_a_job_is_written_and_downloaded_in_the_chosen_format(client, docx_book, tmp_path):
    j = client.post("/api/jobs", files={"file": ("My Book.docx", docx_book.read_bytes())}).json()
    start = {"api_key": KEY, "auto_glossary": False}
    assert client.post(f"/api/jobs/{j['id']}/start", json={**start, "output_format": "mobi"}).status_code == 400
    assert client.post(f"/api/jobs/{j['id']}/start", json={**start, "output_format": "epub"}).status_code == 200
    done = finished(client, j["id"])
    assert done["state"] == "done" and done["output_format"] == "epub" and done["download_name"] == "My Book_bilingual.epub"
    r = client.get(f"/api/jobs/{j['id']}/download")
    assert r.status_code == 200 and r.headers["content-type"] == "application/epub+zip"
    (tmp_path / "got.epub").write_bytes(r.content)
    assert "table" in kinds(read_blocks(tmp_path / "got.epub", tmp_path / "g"))


def test_markdown_with_pictures_is_downloaded_as_a_zip_named_after_the_book(client, md_book):
    import io
    j = client.post("/api/jobs", files={"file": ("book.md", md_book.read_bytes())}).json()
    # the picture is not uploaded with the text, so the text alone comes back as .md
    client.post(f"/api/jobs/{j['id']}/start", json={"api_key": KEY, "auto_glossary": False, "output_format": "md"})
    assert finished(client, j["id"])["download_name"] == "book_bilingual.md"
    assert client.post("/api/jobs", files={"file": ("w.docx", b"")}).status_code == 400  # not a book


def test_a_word_book_with_a_picture_as_markdown_is_a_zip(client, docx_book):
    import io
    j = client.post("/api/jobs", files={"file": ("w.docx", docx_book.read_bytes())}).json()
    client.post(f"/api/jobs/{j['id']}/start", json={"api_key": KEY, "auto_glossary": False, "output_format": "md"})
    assert finished(client, j["id"])["download_name"] == "w_bilingual.zip"
    with zipfile.ZipFile(io.BytesIO(client.get(f"/api/jobs/{j['id']}/download").content)) as z:
        names = z.namelist()
        text = z.read("w_bilingual.md").decode("utf-8")
    assert any(n.startswith("w_bilingual_assets/") for n in names) and "](w_bilingual_assets/" in text
