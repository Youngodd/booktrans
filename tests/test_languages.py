"""Any-language translation: detection, target choice, output modes, and the garbled-text fix."""
import sys

import fitz
import pytest
from pypdf import PdfReader

import booktrans.backends as backends
from booktrans import cli, languages, prompts
from booktrans.layout import extract_blocks, render_layout_page
from booktrans.pipeline import default_output, detect_book_language, translate_book
from booktrans.readers import decode_text
from booktrans.textclean import clean_text
from booktrans.writer import text_pages
from tests.conftest import FakeBackend

FR = ("Le petit prince est un conte poétique et philosophique. Il raconte l'histoire d'un pilote "
      "qui rencontre dans le désert un enfant venu d'une autre planète, et ce que les hommes "
      "ont oublié de la vie, de l'amitié et de l'amour dans les villes.")
EN = ("The little prince is a poetic and philosophical tale. It tells the story of a pilot who "
      "meets in the desert a child from another planet, and what people have forgotten about "
      "life, friendship and love in the cities of the world.")
SYMBOLS = "© ™ → • ≈ ½ é ñ ü Ω ★ ✓ ✔ ± ° § ¶ † ‡ № ♥"


def pages_of(path):
    return len(PdfReader(str(path)).pages)


def page_text(path, n):
    return PdfReader(str(path)).pages[n].extract_text() or ""


def ink(pdf_bytes, rect=None):
    """Number of dark pixels on the first page of a PDF."""
    with fitz.open("pdf", pdf_bytes) as d:
        pix = d[0].get_pixmap(dpi=72, clip=rect)
    samples = pix.samples  # a property that copies the buffer: read it once
    return sum(1 for i in range(0, len(samples), pix.n) if samples[i] < 100)


# ---- detection -------------------------------------------------------------------------

@pytest.mark.parametrize("text,code", [
    (EN * 2, "en"), (FR * 2, "fr"),
    ("これは日本語のテストです。漢字とひらがなとカタカナを使います。私は学校へ行きます。" * 2, "ja"),
    ("이것은 한국어 테스트입니다. 우리는 오늘 학교에 갑니다. 그리고 집에 옵니다." * 2, "ko"),
    ("这是一个中文测试，我们今天去学校读书，然后回家吃饭。这个书很有意思。" * 2, "zh-CN"),
    ("這是一個繁體中文測試，我們今天去學校讀書，然後回家吃飯。這個書很有意思。" * 2, "zh-TW"),
    ("Это тест на русском языке. Мы идём в школу и читаем книги вместе. " * 3, "ru"),
    ("هذا اختبار باللغة العربية. نحن نذهب إلى المدرسة ونقرأ الكتب معا. " * 3, "ar"),
    ("यह हिंदी भाषा का परीक्षण है। हम आज स्कूल जाते हैं और किताबें पढ़ते हैं। " * 3, "hi"),
])
def test_detect_language(text, code):
    assert languages.detect_language(text) == code


def test_detect_language_is_unsure_instead_of_guessing():
    assert languages.detect_language("") is None
    assert languages.detect_language("12345 6789 ***") is None
    assert languages.detect_language("Hello there") is None  # too short to tell


def test_detection_samples_the_whole_book_not_just_the_cover():
    cover = ["Ein Buch"] + [""]  # front matter in another language
    pages = cover + [FR] * 40
    assert languages.detect_language(languages.sample_pages(pages)) == "fr"


def test_detect_book_language_from_a_pdf(tmp_path):
    doc = fitz.open()
    for _ in range(3):
        doc.new_page().insert_textbox(fitz.Rect(40, 40, 550, 400), FR, fontsize=11)
    doc.save(tmp_path / "fr.pdf")
    assert detect_book_language(tmp_path / "fr.pdf") == "fr"


def test_unknown_languages_are_refused():
    with pytest.raises(ValueError):
        languages.check_target("tlh")
    assert languages.check_target("ZH-cn") == "zh-CN" and languages.check_source(None) == "auto"


# ---- prompts ---------------------------------------------------------------------------

def test_prompts_name_the_source_and_target_language():
    for build in (prompts.system_prompt, prompts.layout_prompt, prompts.glossary_prompt):
        p = build("fr", "ar")
        assert "French" in p and "Arabic" in p and "Chinese" not in p
    assert "Simplified Chinese" in prompts.system_prompt("en", "zh-CN")
    assert "identify" in prompts.system_prompt("auto", "en")  # unknown source: the model decides


def test_the_backend_receives_the_chosen_languages(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text(FR, encoding="utf-8")
    systems = []

    class Spy(FakeBackend):
        def complete(self, system, user, max_tokens=4096):
            systems.append(system)
            return "x"
    translate_book(f, tmp_path / "o.pdf", Spy(), target="ja", source="fr", auto_glossary=False)
    assert systems and all("French" in s and "Japanese" in s for s in systems)


def test_glossary_is_skipped_for_scripts_without_capitalised_names(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("これは日本語のテストです。漢字とひらがなとカタカナを使います。" * 5, encoding="utf-8")
    b = FakeBackend()
    translate_book(f, tmp_path / "o.pdf", b, target="en")
    assert not any(" | " in c for c in b.calls)


# ---- cache keyed by target language ----------------------------------------------------

def test_cache_is_separate_per_target_language(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("Hello world.\n\nSecond.", encoding="utf-8")
    out = tmp_path / "o.pdf"
    first = FakeBackend()
    translate_book(f, out, first, target="fr", auto_glossary=False)
    assert first.calls
    again = FakeBackend()
    translate_book(f, out, again, target="fr", auto_glossary=False)
    assert again.calls == []  # same target: from the cache
    other = FakeBackend()
    translate_book(f, out, other, target="de", auto_glossary=False)
    assert other.calls  # another target never reuses the French translation
    zh = FakeBackend()
    translate_book(f, out, zh, auto_glossary=False)
    assert zh.calls  # the default target has its own entries too


def test_glossary_file_is_per_target(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("Boyle met Newton. Boyle liked Newton. Boyle and Newton wrote.", encoding="utf-8")
    out = tmp_path / "o.pdf"
    translate_book(f, out, FakeBackend(), target="fr")
    assert out.with_suffix(".glossary.fr.json").exists()
    assert not out.with_suffix(".glossary.json").exists()


# ---- output modes ----------------------------------------------------------------------

def test_default_output_name_follows_the_mode(tmp_path):
    assert default_output(tmp_path / "a.pdf").name == "a_bilingual.pdf"
    assert default_output(tmp_path / "a.pdf", "1-3", "target-only", "ja").name == "a_ja pages 1-3.pdf"


def test_bilingual_vs_target_only_page_order(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("First page text.\n\n" + "x" * 1800 + "\n\nSecond page text.", encoding="utf-8")
    b = FakeBackend(reply=lambda u: "TRANS<" + u[:6] + ">")
    both, only = tmp_path / "both.pdf", tmp_path / "only.pdf"
    translate_book(f, both, b, target="fr", output_mode="bilingual", auto_glossary=False, state=both)
    translate_book(f, only, b, target="fr", output_mode="target-only", auto_glossary=False, state=both)
    assert pages_of(both) == 6 and pages_of(only) == 3  # three source pages
    for n in range(3):  # original, translation, original, translation...
        assert "TRANS" not in page_text(both, 2 * n) and "TRANS" in page_text(both, 2 * n + 1)
    assert "First" in page_text(both, 0) and "Second" in page_text(both, 4)
    assert all("TRANS" in page_text(only, n) for n in range(3))
    assert not any("First page" in page_text(only, n) for n in range(3))


def test_target_only_pdf_redraws_pages_and_keeps_pages_without_text(text_pdf, tmp_path):
    src = fitz.open(str(text_pdf))
    src.new_page()  # a picture-only or blank page: nothing to translate
    src.save(tmp_path / "b.pdf")
    out = tmp_path / "o.pdf"
    translate_book(tmp_path / "b.pdf", out, FakeBackend(), output_mode="target-only")
    assert pages_of(out) == 4  # 3 translated pages + the blank page copied as it is
    both = tmp_path / "both.pdf"
    translate_book(tmp_path / "b.pdf", both, FakeBackend(), state=out)
    assert pages_of(both) == 8  # 4 originals, each followed by a page (the blank one by a dash)


def test_changing_only_the_output_mode_reuses_the_cache(tmp_path, monkeypatch):
    f = tmp_path / "a.txt"
    f.write_text("Hello world.\n\nSecond.", encoding="utf-8")
    backend = FakeBackend()
    monkeypatch.setitem(backends.BACKENDS, "fake", lambda: (lambda model=None, usage=None: backend))

    def run(*argv):
        monkeypatch.setattr(sys, "argv", ["x", str(f), "--backend", "fake", "--target", "fr", *argv])
        cli.main()
    run()
    assert backend.calls
    backend.calls.clear()
    run("--output-mode", "target-only")
    assert backend.calls == []  # only the PDF was rebuilt
    assert (tmp_path / "a_bilingual.pdf").exists() and (tmp_path / "a_fr.pdf").exists()
    assert pages_of(tmp_path / "a_fr.pdf") == 1


def test_cli_rejects_unknown_language(tmp_path, monkeypatch):
    f = tmp_path / "a.txt"
    f.write_text("Hi", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["x", str(f), "--target", "tlh"])
    with pytest.raises(SystemExit):
        cli.main()


# ---- the garbled-text bug --------------------------------------------------------------

def test_every_special_symbol_is_drawn():
    """Regression: the old CJK-only font drew a wrong glyph or nothing for these."""
    for ch in SYMBOLS.split():
        assert ink(text_pages(ch + ch + ch, "x", "zh-CN")) > ink(text_pages("", "x", "zh-CN")) + 20, ch


def test_symbols_survive_into_the_pdf_text(tmp_path):
    out = tmp_path / "o.pdf"
    from booktrans.writer import make_pdf
    make_pdf(["x"], ["版权所有 " + SYMBOLS], out, mode="target-only")
    text = page_text(out, 0)
    for ch in SYMBOLS.split():
        assert ch in text, ch
    assert "�" not in text


def test_text_that_cannot_be_drawn_is_removed_not_garbled():
    assert clean_text("a�b\x00c​de\ud800f﻿g") == "abcdefg"
    assert clean_text("क्ष‍त्र") == "क्ष‍त्र"  # joiners that shape Hindi stay
    assert clean_text("a\tb\nc") == "a b\nc"


def test_arabic_hindi_japanese_korean_are_drawn():
    for lang, text in [("ar", "مرحبا بالعالم هذا اختبار"), ("hi", "यह हिंदी भाषा का परीक्षण है"),
                       ("ja", "これは日本語のテストです"), ("ko", "이것은 한국어 테스트입니다"),
                       ("ru", "Это тест на русском языке")]:
        assert ink(text_pages(text, "x", lang)) > ink(text_pages("", "x", lang)) + 100, lang


def test_arabic_page_is_right_aligned():
    with fitz.open("pdf", text_pages("مرحبا", "x", "ar")) as d:
        words = [w for w in d[0].get_text("words") if "مرحبا" in w[4] or w[4]]
    body = max(words, key=lambda w: w[3])  # the lowest line: the body text, not the label
    assert body[2] > 400  # ends at the right margin


def test_a_symbol_only_block_keeps_its_ink_and_draws_no_tilde(tmp_path):
    doc = fitz.open()
    pg = doc.new_page()
    pg.insert_text((72, 100), "A proper heading here", fontsize=18)
    doc.save(tmp_path / "s.pdf")
    with fitz.open(str(tmp_path / "s.pdf")) as d:
        blocks = extract_blocks(d[0])
    out = render_layout_page(tmp_path / "s.pdf", 0, blocks, ["~"] * len(blocks))
    with fitz.open("pdf", out) as d:
        assert "~" not in d[0].get_text() and "proper heading" in d[0].get_text()


def test_in_place_page_draws_symbols_and_rtl(text_pdf):
    with fitz.open(str(text_pdf)) as d:
        blocks = extract_blocks(d[0])
    for target, text in (("zh-CN", "版权 © ™ → 😀"), ("ar", "مرحبا بالعالم © ™")):
        out = render_layout_page(text_pdf, 0, blocks, [text] * len(blocks), target)
        assert fitz.open("pdf", out)[0].get_text().strip()


def test_japanese_source_blocks_are_found(tmp_path):
    doc = fitz.open()
    doc.new_page().insert_text((72, 100), "これは日本語の見出しです", fontsize=16, fontname="japan")
    doc.save(tmp_path / "ja.pdf")
    with fitz.open(str(tmp_path / "ja.pdf")) as d:
        assert extract_blocks(d[0])  # the old Latin-only filter dropped every block


def test_legacy_encoded_text_files_are_decoded():
    cases = [("gbk", "这是一个中文测试文件，用于检查编码。我们今天去学校读书，然后回家吃饭睡觉。"),
             ("shift_jis", "これは日本語のテストです。漢字とひらがなとカタカナを使います。私は学校へ行きます。"),
             ("cp1251", "Это тест на русском языке. Мы идём в школу и читаем книги вместе."),
             ("cp1252", "Voilà l'été, où ça va être très bien — « oui ». Nous irons à l'école demain matin.")]
    for enc, text in cases:
        assert decode_text(text.encode(enc)) == text, enc
    assert decode_text("﻿héllo".encode("utf-8")) == "héllo"


# ---- web API ---------------------------------------------------------------------------

@pytest.fixture
def client(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from fastapi.testclient import TestClient
    from booktrans.web.app import create_app
    pool = ThreadPoolExecutor(max_workers=1)
    yield TestClient(create_app(tmp_path / "data", executor=pool,
                                backend_factory=lambda key, provider="api", **kw: FakeBackend()))
    pool.shutdown(wait=True)


KEY = "sk-ant-test-1234567890abcdefghij"


def wait_done(client, job_id):
    import time
    for _ in range(400):
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["state"] in ("done", "failed"):
            return j
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_api_lists_languages_and_detects_the_upload(client):
    cfg = client.get("/api/config").json()
    codes = [l["code"] for l in cfg["languages"]]
    assert {"en", "zh-CN", "zh-TW", "ja", "ko", "es", "fr", "de", "pt", "ru", "ar", "hi", "it"} <= set(codes)
    assert cfg["default_target"] == "zh-CN"
    job = client.post("/api/jobs", files={"file": ("livre.txt", (FR * 2).encode())}).json()
    assert job["detected_language"] == "fr"


def test_api_start_takes_target_and_output_mode(client):
    job = client.post("/api/jobs", files={"file": ("a.txt", b"Hello world.\n\nSecond.")}).json()
    r = client.post(f"/api/jobs/{job['id']}/start",
                    json={"api_key": KEY, "target": "ja", "source": "en", "output_mode": "target-only"})
    assert r.status_code == 200 and r.json()["target"] == "ja"
    done = wait_done(client, job["id"])
    assert done["state"] == "done" and done["output_mode"] == "target-only"
    r = client.get(f"/api/jobs/{job['id']}/download")
    assert "a_ja.pdf" in r.headers["content-disposition"]
    assert len(PdfReader(__import__("io").BytesIO(r.content)).pages) == 1


def test_api_rejects_unknown_language_and_mode(client):
    job = client.post("/api/jobs", files={"file": ("a.txt", b"Hello")}).json()
    for body in ({"target": "tlh"}, {"source": "tlh"}, {"output_mode": "both"}):
        r = client.post(f"/api/jobs/{job['id']}/start", json={"api_key": KEY, **body})
        assert r.status_code == 400
