import sys
import pytest
from pypdf import PdfReader
import booktrans.backends as backends
from booktrans import cli
from booktrans.layout import collect_layout, extract_blocks
from tests.conftest import FakeBackend


@pytest.fixture
def run(monkeypatch):
    def _run(*argv, backend=None):
        backend = backend or FakeBackend()
        monkeypatch.setitem(backends.BACKENDS, "fake",
                            lambda: (lambda model=None, usage=None: backend))
        monkeypatch.setattr(sys, "argv", ["x", *argv, "--backend", "fake"])
        cli.main()
        return backend
    return _run


def pages(path):
    return len(PdfReader(str(path)).pages)

def test_extract_blocks(text_pdf):
    import fitz
    with fitz.open(str(text_pdf)) as d:
        blocks = extract_blocks(d[0])
    assert any("Chapter heading 0" in b["text"] for b in blocks)

def test_collect_layout_context(text_pdf):
    layout, ctx = collect_layout(text_pdf, [0, 1, 2])
    assert set(layout) == {0, 1, 2}
    assert ctx[0][0] == "" and "Chapter heading 1" in ctx[0][1]
    assert "Chapter heading 1" in ctx[2][0] and ctx[2][1] == ""

def test_pdf_layout_end_to_end(run, text_pdf, tmp_path):
    out = tmp_path / "o.pdf"
    run(str(text_pdf), "-o", str(out))
    assert pages(out) == 6

def test_pdf_page_range(run, text_pdf, tmp_path):
    out = tmp_path / "o.pdf"
    run(str(text_pdf), "-o", str(out), "--pages", "2-3")
    assert pages(out) == 4
    assert not out.with_suffix(".src.pdf").exists()

def test_pdf_flat(run, text_pdf, tmp_path):
    out = tmp_path / "o.pdf"
    fake = run(str(text_pdf), "-o", str(out), "--flat")
    assert pages(out) == 6
    assert all(not c.startswith("[1]") for c in fake.calls)

def test_second_run_uses_cache(run, text_pdf, tmp_path):
    out = tmp_path / "o.pdf"
    run(str(text_pdf), "-o", str(out))
    assert run(str(text_pdf), "-o", str(out)).calls == []

def test_txt_end_to_end(run, tmp_path):
    f = tmp_path / "a.txt"; f.write_text("Hello world.\n\nSecond.")
    run(str(f), "-o", str(tmp_path / "o.pdf"))
    assert pages(tmp_path / "o.pdf") == 2

def test_default_output_name_has_range(run, tmp_path):
    f = tmp_path / "a.txt"; f.write_text("Hello")
    run(str(f), "--pages", "1")
    assert (tmp_path / "a_bilingual pages 1.pdf").exists()

def test_ocr_rejects_text_only_backend(run, text_pdf, tmp_path):
    with pytest.raises(SystemExit):
        run(str(text_pdf), "-o", str(tmp_path / "o.pdf"), "--ocr")

def test_ocr_flow_with_vision_backend(run, tmp_path):
    import fitz
    p = tmp_path / "scan.pdf"
    d = fitz.open(); d.new_page(); d.save(p)
    class V(FakeBackend):
        supports_vision = True
        def ocr_image(self, jpeg, prompt): return "Scanned text on the page here."
    run(str(p), "-o", str(tmp_path / "o.pdf"), "--ocr", backend=V())
    assert (tmp_path / "o.ocr.json").exists()
    assert pages(tmp_path / "o.pdf") == 2

def test_empty_translation_cover(tmp_path):
    from booktrans.writer import make_pdf
    make_pdf(["a", "b"], ["", ""], tmp_path / "o.pdf")
    assert pages(tmp_path / "o.pdf") == 3


def test_scanned_page_english_is_erased(tmp_path):
    """Scan = full-page image + invisible OCR text: the printed English must go."""
    import fitz
    from booktrans.layout import render_layout_page
    src = fitz.open(); pg = src.new_page(width=300, height=300)
    pg.draw_rect(pg.rect, color=None, fill=(0.85, 0.82, 0.7))
    pg.insert_text((40, 100), "Printed English words", fontsize=16, color=(0, 0, 0))
    pix = pg.get_pixmap(dpi=72)
    scan = fitz.open(); sp = scan.new_page(width=300, height=300)
    sp.insert_image(sp.rect, pixmap=pix)
    sp.insert_text((40, 100), "Printed English words", fontsize=16, render_mode=3)
    path = tmp_path / "scan.pdf"; scan.save(path)

    with fitz.open(str(path)) as d:
        blocks = extract_blocks(d[0])
    assert blocks
    out = render_layout_page(path, 0, blocks, [""] * len(blocks))  # draw no Chinese
    region = fitz.Rect(blocks[0]["bbox"])
    res = fitz.open("pdf", out)[0].get_pixmap(dpi=72, clip=region)
    dark = [1 for i in range(0, len(res.samples), res.n) if res.samples[i] < 80]
    assert not dark
