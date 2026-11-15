"""Edge cases of the command line (docs/edge-case-test-plan.md, area 5): option conflicts, odd names, damaged books."""
import os

import fitz
import pytest

from booktrans import cli
from tests.conftest import FakeBackend

BOOK = "# Title\n\nHello there, this is a short book that has something to translate.\n"


@pytest.fixture
def go(monkeypatch, tmp_path):
    """Run the command line on a real (tiny) book with the fake backend; returns the exit text or None."""
    monkeypatch.setattr(cli, "make_backend", lambda *a, **k: FakeBackend())
    monkeypatch.setattr("sys.stdin", type("S", (), {"isatty": lambda self: False})())

    def run(*argv, book="book.md", text=BOOK):
        path = tmp_path / book
        if not path.exists():
            path.write_text(text, encoding="utf-8")
        monkeypatch.setattr("sys.argv", ["booktrans", str(path), "--backend", "api", "--no-auto-glossary", *argv])
        try:
            cli.main()
        except SystemExit as e:
            return str(e.code) if e.code not in (0, None) else None
        return None
    run.dir = tmp_path
    return run


def test_the_output_name_and_the_format_option_must_agree(go):
    said = go("-o", str(go.dir / "out.docx"), "--to", "md")
    assert said and "disagree" in said
    assert not (go.dir / "out.docx").exists()  # a Markdown text is never written into a .docx name


@pytest.mark.parametrize("name,fmt", [("out.md", "md"), ("out.markdown", "md"), ("out.DOCX", "docx"), ("OUT.Epub", "epub")])
def test_the_format_follows_the_output_name_whatever_its_case(go, name, fmt):
    assert go("-o", str(go.dir / name)) is None
    assert (go.dir / name).is_file()


@pytest.mark.parametrize("flag", ["md", "MD", "Docx"])
def test_the_format_option_is_not_case_sensitive(go, flag):
    assert go("--to", flag, "-o", str(go.dir / f"o_{flag}.{flag.lower()}")) is None


def test_an_output_name_with_an_unknown_extension_is_refused_unless_the_format_is_given(go):
    said = go("-o", str(go.dir / "out.xyz"))
    assert said and "Cannot write" in said
    assert go("-o", str(go.dir / "out.xyz"), "--to", "md") is None
    assert (go.dir / "out.xyz").read_text(encoding="utf-8").startswith("# ")


def test_an_output_name_with_no_extension_is_a_pdf(go):
    assert go("-o", str(go.dir / "plainname")) is None
    assert (go.dir / "plainname").read_bytes().startswith(b"%PDF")


def test_an_output_folder_that_does_not_exist_is_made(go):
    assert go("-o", str(go.dir / "no" / "such" / "folder" / "o.md")) is None
    assert (go.dir / "no" / "such" / "folder" / "o.md").is_file()


def test_an_output_folder_that_cannot_be_made_is_a_clean_error_not_a_traceback(go):
    (go.dir / "afile").write_text("x")
    said = go("-o", str(go.dir / "afile" / "o.md"))
    assert said and "Cannot write to the folder" in said
    assert not (go.dir / "afile" / "o.md").exists()


@pytest.mark.skipif(os.name == "nt" or hasattr(os, "geteuid") and os.geteuid() == 0,
                    reason="read-only folders are not enforced here")
def test_a_read_only_output_folder_is_found_before_anything_is_paid_for(go):
    folder = go.dir / "locked"
    folder.mkdir()
    folder.chmod(0o555)
    try:
        said = go("-o", str(folder / "o.md"))
    finally:
        folder.chmod(0o755)
    assert said and "read-only" in said


def test_a_book_path_with_spaces_and_chinese_works(go):
    assert go("--to", "md", book="我的 书 第一章.md") is None
    assert (go.dir / "我的 书 第一章_bilingual.md").is_file()


@pytest.mark.parametrize("flags", [["--apply-glossary", "--finish-partial"], ["--pages", "0"], ["--pages", "9-1"],
                                   ["--pages", "7"], ["--redo", "x"], ["--source", "zz"], ["--target", "zz"],
                                   ["--glossary", "does-not-exist.txt"], ["--max-spend", "-5"]])
def test_senseless_option_combinations_exit_with_a_message(go, flags):
    said = go(*flags)
    assert said and "Traceback" not in said


def test_finish_partial_before_anything_was_translated_says_so(go):
    said = go("--finish-partial")
    assert said and "Nothing has been translated" in said


def test_ocr_with_a_text_only_backend_is_refused_before_any_work(go):
    said = go("--ocr")
    assert said and "vision" in said


@pytest.mark.parametrize("name,text", [("a.md", BOOK), ("a.txt", "Plain text of a short book, long enough to read.\n"),
                                       ("a.docx", None), ("a.epub", None), ("a.pdf", None)])
def test_recommend_works_on_every_kind_of_book_and_spends_nothing(go, capsys, name, text):
    path = go.dir / name
    if name.endswith(".docx"):
        import docx
        d = docx.Document()
        d.add_paragraph("A paragraph of text in a Word file for the recommendation.")
        d.save(str(path))
    elif name.endswith(".epub"):
        from ebooklib import epub
        b = epub.EpubBook()
        b.set_identifier("x"); b.set_title("T"); b.set_language("en")
        c = epub.EpubHtml(title="c", file_name="c.xhtml", lang="en", content="<p>A paragraph of text in an EPUB.</p>")
        b.add_item(c); b.spine = [c]; b.add_item(epub.EpubNcx()); b.add_item(epub.EpubNav())
        epub.write_epub(str(path), b)
    elif name.endswith(".pdf"):
        d = fitz.open()
        d.new_page().insert_text((72, 100), "A page of text in a PDF file for the recommendation, long enough.")
        d.save(str(path))
    else:
        path.write_text(text, encoding="utf-8")
    assert go("--recommend", book=name) is None
    out = capsys.readouterr().out
    assert "Suggested settings" in out and "--output-mode" in out


@pytest.mark.parametrize("name,body", [("bad.pdf", b"%PDF-1.4 truncated"), ("bad.docx", b"not a zip"),
                                       ("bad.epub", b""), ("bad.pdf", b"")])
def test_a_damaged_book_is_a_clean_exit_for_both_recommend_and_translate(go, name, body):
    (go.dir / name).write_bytes(body)
    for extra in (["--recommend"], []):
        said = go(*extra, book=name)
        assert said and "Traceback" not in said


def test_a_password_protected_pdf_says_so(go):
    d = fitz.open()
    d.new_page().insert_text((72, 100), "A page of text in a locked PDF file, long enough to read.")
    d.save(str(go.dir / "locked.pdf"), encryption=fitz.PDF_ENCRYPT_RC4_128, owner_pw="o", user_pw="u")
    for extra in (["--recommend"], []):
        said = go(*extra, book="locked.pdf")
        assert said and "password" in said.lower()
