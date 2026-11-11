"""Edge cases: empty, malformed, oversized and hostile input, failing providers, resume."""
import json
import math

import pytest

from booktrans import glossary, languages, readers, spend, translate, usage
from booktrans.backends.base import AuthError, BackendError
from booktrans.fsutil import read_json, write_json
from booktrans.textclean import clean_text
from tests.conftest import FakeBackend


# ---- spend meter: a damaged file or a bad limit must never switch the guard off -------------

@pytest.mark.parametrize("body", ["[1]", "5", "null", '{"spent_cny": null}', '{"spent_cny": "abc"}',
                                  '{"spent_cny": "nan"}', '{"spent_cny": -3}', '{"spent_cny": 1e999}',
                                  "{broken", ""])
def test_meter_ignores_a_damaged_spend_file(tmp_path, body):
    p = tmp_path / "s.json"
    p.write_text(body)
    m = spend.Meter(5, p)
    assert m.spent == 0.0


def test_meter_reads_a_good_spend_file(tmp_path):
    p = tmp_path / "s.json"
    p.write_text('{"spent_cny": 2.5}')
    assert spend.Meter(5, p).spent == 2.5


@pytest.mark.parametrize("limit", [-1, float("nan"), float("inf"), float("-inf")])
def test_meter_rejects_a_senseless_limit(limit):
    with pytest.raises(ValueError):
        spend.Meter(limit)


@pytest.mark.parametrize("limit", [0, None])
def test_meter_zero_or_none_means_no_limit(limit):
    m = spend.Meter(limit)
    m.spent = 1e9
    m.check("api", "text", 10**6, 4096)  # does not raise


def test_meter_stops_exactly_at_the_limit():
    m = spend.Meter(1.0, prices={"p": {"text": (1e6, 1e6)}})
    m.spent = 1.0
    with pytest.raises(spend.SpendLimitReached):
        m.check("p", "text", 3, 4096)


def test_meter_unknown_provider_costs_nothing():
    assert spend.Meter(5).cost("nobody", "text", {"input_tokens": 10**9}) == 0.0


@pytest.mark.parametrize("spent,done,total", [(0, 3, 10), (5, 0, 10), (5, 10, 10), (5, 11, 10),
                                              (float("inf"), 1, 10), (float("nan"), 1, 10), (5, 3, 0)])
def test_rest_estimate_unknowable_cases(spent, done, total):
    assert spend.rest_estimate(spent, done, total) is None


# ---- glossary files ------------------------------------------------------------------------

def test_glossary_file_with_utf8_bom(tmp_path):
    p = tmp_path / "g.txt"
    p.write_bytes("﻿Boyle=波义耳\r\nOxford=牛津\r\n".encode("utf-8"))  # what Windows Notepad writes
    assert glossary.parse_file(p) == {"Boyle": "波义耳", "Oxford": "牛津"}


def test_glossary_file_comments_blanks_and_odd_lines(tmp_path):
    p = tmp_path / "g.txt"
    p.write_text("# a comment\n\n  \nBoyle = 波义耳  # trailing\nonlykey\n=novalue\nkey=\nA=b=c\nX\tY\n",
                 encoding="utf-8")
    assert glossary.parse_file(p) == {"Boyle": "波义耳", "A": "b=c", "X": "Y"}


def test_glossary_file_empty(tmp_path):
    p = tmp_path / "g.txt"
    p.write_text("", encoding="utf-8")
    assert glossary.parse_file(p) == {}


def test_glossary_file_not_utf8_is_a_value_error(tmp_path):
    p = tmp_path / "g.txt"
    p.write_bytes(b"Boyle=\xff\xfe\n")
    with pytest.raises(ValueError):  # the command line reports a ValueError as a message
        glossary.parse_file(p)


def test_glossary_candidates_edge_inputs():
    assert glossary.candidates([]) == []
    assert glossary.candidates([""]) == []
    assert glossary.candidates(["we met Boyle. Later Boyle left."])[0][0] == "Boyle"


def test_glossary_mentioned_handles_regex_characters_in_a_term():
    assert glossary.mentioned("C++", "I write C++ daily")
    assert not glossary.mentioned("Bo", "Boyle")                      # not inside a longer word
    assert glossary.mentioned("Kekulé", "Then Kekulé said")


def test_glossary_note_empty_cases():
    assert glossary.note({}, "Boyle") == ""
    assert glossary.note({"Boyle": ""}, "Boyle") == ""                # "" means no fixed rendering
    assert glossary.note({"Boyle": "波义耳"}, "nothing here") == ""


def test_glossary_build_survives_a_garbage_reply():
    fb = FakeBackend(reply="I cannot help with that.")
    g = {}
    added = glossary.build(fb, ["Boyle met Boyle. Boyle again."], ["Boyle met Boyle."], g)
    assert added == {} and g == {}


def test_glossary_build_keeps_what_was_paid_for_when_a_later_chunk_fails(monkeypatch):
    monkeypatch.setattr(glossary, "CHUNK", 1)
    monkeypatch.setattr(translate, "RETRY_DELAYS", (0,))
    calls = []

    def reply(user):
        calls.append(user)
        if len(calls) > 1:
            raise BackendError("down")
        return "[1] 译"
    text = "Alpha met Alpha. Beta met Beta. " * 2
    g = {}
    glossary.build(FakeBackend(reply=reply), [text], [text], g)
    assert len(g) == 1  # the first chunk is kept


# ---- text cleaning ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,clean", [
    ("", ""),
    ("a\r\nb", "a\nb"),
    ("a\rb", "a\nb"),                      # old Mac line ends must not glue two words
    ("a\x85b", "a\nb"),
    ("a\x0cb\x0bc\td", "a b c d"),         # form feed, vertical tab, tab are spaces
    ("a\u2028b\u2029c", "a\nb\nc"),            # line and paragraph separators
    ("a\u00a0b", "a\u00a0b"),
    ("a​b﻿c", "abc"),            # zero-width space, BOM
    ("a�b", "ab"),
    ("a\ud800b", "ab"),                    # lone surrogate
    ("ab", "ab"),                    # private use
    ("é", "é"),                      # NFC
    ("👨‍👩‍👧", "👨‍👩‍👧"),  # joiners of an emoji sequence stay
    ("مرحبا‏x", "مرحبا‏x"),      # bidi mark stays
])
def test_clean_text_cases(raw, clean):
    assert clean_text(raw) == clean


# ---- usage log ---------------------------------------------------------------------------------

@pytest.mark.parametrize("old", ["{broken", "", "{}", "5", "null", "\x00\x01"])
def test_usage_report_survives_a_damaged_log(tmp_path, old, capsys):
    u = usage.Usage()
    u.record({"input_tokens": 3, "output_tokens": 4})
    (tmp_path / "o.usage.json").write_text(old)
    u.report(tmp_path / "o.pdf")
    runs = json.loads((tmp_path / "o.usage.json").read_text())
    assert runs[-1]["input_tokens"] == 3


def test_usage_report_appends_runs(tmp_path):
    for _ in range(2):
        u = usage.Usage()
        u.record({"input_tokens": 1})
        u.report(tmp_path / "o.pdf")
    assert len(json.loads((tmp_path / "o.usage.json").read_text())) == 2


def test_usage_record_accepts_objects_and_missing_fields():
    class Obj:
        input_tokens = 7
        output_tokens = None
    u = usage.Usage()
    u.record(Obj())
    u.record({})
    assert u.calls == 2 and u.tokens["input_tokens"] == 7 and u.tokens["output_tokens"] == 0


# ---- json helpers ----------------------------------------------------------------------------

@pytest.mark.parametrize("body", ["[1,2]", "5", "null", '"s"', "{broken", ""])
def test_read_json_returns_empty_dict_for_anything_but_an_object(tmp_path, body):
    p = tmp_path / "c.json"
    p.write_text(body)
    assert read_json(p) == {}


def test_read_json_missing_file(tmp_path):
    assert read_json(tmp_path / "none.json") == {}


def test_write_json_leaves_no_temp_file_and_keeps_unicode(tmp_path):
    p = tmp_path / "c.json"
    write_json(p, {"k": "波义耳 ✓"})
    assert read_json(p) == {"k": "波义耳 ✓"}
    assert "波义耳" in p.read_text(encoding="utf-8")            # not \u-escaped
    assert [f.name for f in tmp_path.iterdir()] == ["c.json"]


# ---- reading books ---------------------------------------------------------------------------

def test_txt_empty_and_whitespace_only(tmp_path):
    for body in ("", "   \n\n \t\n"):
        (tmp_path / "e.txt").write_text(body)
        assert readers.read_txt(tmp_path / "e.txt") == []


def test_txt_with_single_newlines_is_still_split_into_pages(tmp_path):
    """A book with one line break per line has no blank lines: it must not become one huge page."""
    lines = [f"Line number {n} of a book that has no blank line anywhere in it." for n in range(400)]
    (tmp_path / "b.txt").write_text("\n".join(lines))
    pages = readers.read_txt(tmp_path / "b.txt")
    assert len(pages) > 5
    assert all(len(p) <= readers.CHARS_PER_PAGE * 1.2 for p in pages)
    assert "Line number 0 " in pages[0] and "Line number 399 " in pages[-1]


def test_paginate_oversized_paragraph_without_any_break():
    pages = readers.paginate(["x" * 10_000])
    assert len(pages) >= 5
    assert all(len(p) <= readers.CHARS_PER_PAGE for p in pages)
    assert "".join(pages) == "x" * 10_000


def test_paginate_oversized_paragraph_splits_at_sentences():
    para = " ".join(f"Sentence {n} ends here." for n in range(300))
    pages = readers.paginate([para])
    assert len(pages) > 1
    assert all(p.endswith(".") for p in pages)
    assert " ".join(pages).split() == para.split()                   # nothing lost or duplicated


def test_paginate_keeps_paragraph_order_and_handles_empty():
    assert readers.paginate([]) == []
    pages = readers.paginate(["a" * 1000, "b" * 1000, "c" * 1000])
    assert [p[0] for p in pages] == ["a", "c"] or "".join(pages).count("a") == 1000
    joined = "\n\n".join(pages)
    assert joined.index("a") < joined.index("b") < joined.index("c")


@pytest.mark.parametrize("data,expected", [
    (b"", ""),
    ("﻿hi".encode("utf-8"), "hi"),
    ("hi".encode("utf-16"), "hi"),
    ("hi".encode("utf-16-be").join([b"\xfe\xff", b""]), "hi"),
    ("héllo wörld, ça va?".encode("cp1252"), "héllo wörld, ça va?"),
])
def test_decode_text_cases(data, expected):
    assert readers.decode_text(data) == expected


def test_decode_text_pure_garbage_does_not_raise():
    assert isinstance(readers.decode_text(bytes(range(256)) * 4), str)


def test_unsupported_and_missing_files(tmp_path):
    with pytest.raises(ValueError):
        readers.read_book(tmp_path / "x.docx")
    with pytest.raises(ValueError):
        readers.read_book(tmp_path / "noext")
    with pytest.raises(FileNotFoundError):
        readers.read_book(tmp_path / "missing.txt")


def test_upper_case_extension_is_accepted(tmp_path):
    (tmp_path / "B.TXT").write_text("Hello there, this is a book.")
    assert readers.read_book(tmp_path / "B.TXT")


def test_corrupt_pdf_raises_an_error_not_a_hang(tmp_path):
    (tmp_path / "bad.pdf").write_bytes(b"%PDF-1.4\nnot really a pdf")
    with pytest.raises(Exception):
        readers.read_book(tmp_path / "bad.pdf")


def test_zero_byte_pdf(tmp_path):
    (tmp_path / "z.pdf").write_bytes(b"")
    with pytest.raises(Exception):
        readers.read_book(tmp_path / "z.pdf")


def test_corrupt_epub(tmp_path):
    (tmp_path / "bad.epub").write_bytes(b"PK\x03\x04 broken")
    with pytest.raises(Exception):
        readers.read_book(tmp_path / "bad.epub")


@pytest.mark.parametrize("spec,total,expected", [
    (None, 5, [0, 1, 2, 3, 4]), ("", 5, [0, 1, 2, 3, 4]), ("2", 5, [1]), ("2-3", 5, [1, 2]),
    (" 2 - 3 ", 5, [1, 2]), ("0-2", 5, [0, 1]), ("4-99", 5, [3, 4]), ("99", 5, []), ("0", 5, []),
    ("1-1", 5, [0]), ("1", 0, []),
])
def test_parse_range_valid(spec, total, expected):
    assert readers.parse_range(spec, total) == expected


@pytest.mark.parametrize("spec", ["a", "-1", "5-2", "2-3-4", "1.5", "1,2", "1-", "--"])
def test_parse_range_invalid(spec):
    with pytest.raises(ValueError):
        readers.parse_range(spec, 10)


def test_reflow_edges():
    assert readers.reflow("") == ""
    assert readers.reflow("\n\n\n") == ""
    assert readers.reflow("short\nlines\nstay") == "short\nlines\nstay"
    long = "word " * 30
    assert "\n" not in readers.reflow(long + "\n" + long)


# ---- retries and the model reply ------------------------------------------------------------

@pytest.fixture
def no_sleep(monkeypatch):
    slept = []
    monkeypatch.setattr(translate.time, "sleep", slept.append)
    return slept


def test_complete_retries_then_succeeds(no_sleep):
    state = {"n": 0}

    def reply(user):
        state["n"] += 1
        if state["n"] < 3:
            raise BackendError("blip")
        return "ok"
    assert translate.complete(FakeBackend(reply=reply), "s", "t", 100) == "ok"
    assert no_sleep == [5, 20]


def test_complete_gives_up_after_the_last_retry(no_sleep):
    fb = FakeBackend(reply=lambda u: (_ for _ in ()).throw(BackendError("down")))
    with pytest.raises(BackendError):
        translate.complete(fb, "s", "t", 100)
    assert len(fb.calls) == 4 and no_sleep == [5, 20, 60]


def test_complete_never_retries_an_auth_error_or_a_spend_stop(no_sleep):
    fb = FakeBackend(reply=lambda u: (_ for _ in ()).throw(AuthError("bad key")))
    with pytest.raises(AuthError):
        translate.complete(fb, "s", "t", 100)
    assert len(fb.calls) == 1 and no_sleep == []
    fb = FakeBackend(reply=lambda u: (_ for _ in ()).throw(spend.SpendLimitReached(1, 1)))
    with pytest.raises(spend.SpendLimitReached):
        translate.complete(fb, "s", "t", 100)
    assert len(fb.calls) == 1


def test_translate_blank_text_makes_no_call():
    fb = FakeBackend()
    assert translate.translate(fb, "  \n ") == "" and fb.calls == []


@pytest.mark.parametrize("reply,expect", [
    ("[1] a\n[2] b", ["a", "b"]),
    ("Sure! Here it is:\n[1] a\n[2] b", ["a", "b"]),            # a preamble before the markers
    ("[1]\ta\r\n[2]    b\r\n", ["a", "b"]),                    # tabs, CRLF, extra spaces
    ("[2] b\n[1] a", ["a", "b"]),                              # out of order
    ("[1] **a**\n[2] b**", ["a", "b"]),                        # markdown the prompt forbids
    ("[1] line one\nline two\n[2] b", ["line one\nline two", "b"]),
])
def test_translate_blocks_reads_the_reply(reply, expect):
    fb = FakeBackend(reply=reply)
    assert translate.translate_blocks(fb, [{"text": "x"}, {"text": "y"}]) == expect
    assert len(fb.calls) == 1


def test_translate_blocks_wrong_marker_sets_fall_back_to_one_by_one():
    for reply in ("[1] only one", "[1] a\n[2] b\n[3] c", "[2] b\n[3] c", "nothing useful"):
        fb = FakeBackend(reply=reply)
        out = translate.translate_blocks(fb, [{"text": "x"}, {"text": "y"}])
        assert len(out) == 2 and len(fb.calls) == 4          # two tries, then one call per block


def test_an_empty_answer_never_erases_a_block():
    """"" would redact the original text and draw nothing: the block is kept as it is instead."""
    from booktrans.layout import KEEP
    out = translate.translate_blocks(FakeBackend(reply=""), [{"text": "x"}, {"text": "y"}])
    assert out == [KEEP, KEEP]
    out = translate.translate_blocks(FakeBackend(reply="[1] a\n[2]   "), [{"text": "x"}, {"text": "y"}])
    assert out == ["a", KEEP]


def test_an_empty_translation_of_a_page_is_an_error_not_a_cached_blank(tmp_path):
    fb = FakeBackend(reply="  ")
    with pytest.raises(translate.EmptyReply):
        translate.translate(fb, "Some real text")
    assert len(fb.calls) == 2                                  # one immediate second try
    cp = tmp_path / "c.cache.json"
    with pytest.raises(BackendError):
        translate.translate_all(FakeBackend(reply=""), [0], ["Some real text"], {}, {}, {}, cp)
    assert read_json(cp) == {}                                 # nothing cached, so Continue retries it
    seq = iter(["", "ok"])
    assert translate.translate(FakeBackend(reply=lambda u: next(seq)), "Some real text") == "ok"


def test_translate_blocks_empty_list():
    assert translate.translate_blocks(FakeBackend(), []) == []


def test_translate_blocks_context_is_in_the_request_but_not_required():
    fb = FakeBackend()
    translate.translate_blocks(fb, [{"text": "x"}], ctx=("end of last page", "start of next"))
    assert "end of last page" in fb.calls[0] and "start of next" in fb.calls[0]
    fb = FakeBackend()
    translate.translate_blocks(fb, [{"text": "x"}], ctx=("", ""))
    assert "Context" not in fb.calls[0]


def test_translate_blocks_text_that_looks_like_a_marker():
    fb = FakeBackend(reply="[1] [2] is a footnote mark\n[2] fine")
    out = translate.translate_blocks(fb, [{"text": "[2] footnote"}, {"text": "y"}])
    assert len(out) == 2


# ---- cache keys and resume ------------------------------------------------------------------

def test_cache_key_per_target():
    assert translate.cache_key(3, "zh-CN") == "3"
    assert translate.cache_key(3, "zh-CN", True) == "L3"
    assert translate.cache_key(3, "en") == "en:3"
    assert translate.cache_key(3, "zh-TW", True) == "zh-TW:L3"
    assert len({translate.cache_key(3, t) for t in languages.LANGUAGES}) == len(languages.LANGUAGES)


def test_translate_all_uses_cache_redo_and_survives_a_damaged_cache_file(tmp_path):
    cp = tmp_path / "c.cache.json"
    fb = FakeBackend()
    cache = translate.load_cache(cp)
    translate.translate_all(fb, [0, 1], ["one", "two"], {}, {}, cache, cp)
    assert len(fb.calls) == 2
    translate.translate_all(fb, [0, 1], ["one", "two"], {}, {}, translate.load_cache(cp), cp)
    assert len(fb.calls) == 2                                  # all cached
    translate.translate_all(fb, [0, 1], ["one", "two"], {}, {}, translate.load_cache(cp), cp, redo={1})
    assert len(fb.calls) == 3                                  # only page 1 again
    cp.write_text("{broken")
    assert translate.load_cache(cp) == {}                      # a damaged cache starts over, no crash


def test_translate_all_redoes_a_layout_page_whose_block_count_changed(tmp_path):
    cp = tmp_path / "c.cache.json"
    cache = {"L0": ["only one"]}
    blocks = {0: [{"text": "a"}, {"text": "b"}]}
    fb = FakeBackend()
    translate.translate_all(fb, [0], ["t"], blocks, {0: ("", "")}, cache, cp)
    assert len(cache["L0"]) == 2 and len(fb.calls) == 1


def test_translate_all_stops_cleanly_when_progress_raises(tmp_path):
    from booktrans.pipeline import Cancelled
    cp = tmp_path / "c.cache.json"

    def progress(stage, done, total):
        if done == 2:
            raise Cancelled()
    with pytest.raises(Cancelled):
        translate.translate_all(FakeBackend(), [0, 1, 2], ["a", "b", "c"], {}, {}, {}, cp, progress=progress)
    assert set(read_json(cp)) == {"0", "1"}                    # finished pages are kept


# ---- language detection --------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["", "   ", "12345 67890 " * 10, "😀😀😀😀" * 10, "a", "!!! ??? ..." * 10])
def test_detect_none_for_nothing_to_read(text):
    assert languages.detect_language(text) is None
    assert languages.detect_language([text, text]) is None


def test_detect_mixed_scripts_and_short_text():
    assert languages.detect_language("日本語のテキストです。" * 5) == "ja"
    assert languages.detect_language("한국어 텍스트입니다. " * 5) == "ko"
    assert languages.detect_language("这是一个关于学习的简单测试。" * 5) == "zh-CN"
    assert languages.detect_language("這是一個關於學習的簡單測試。" * 5) == "zh-TW"
    assert languages.detect_language("Привет, это тест языка. " * 5) == "ru"
    assert languages.detect_language("hello") is None          # too little to be sure


def test_detect_a_cover_in_another_language_is_outvoted():
    body = "The history of the world is long and the people in it were many. " * 20
    assert languages.detect_language(["Le Livre"] + [body] * 5) == "en"


def test_check_helpers_normalise_and_reject():
    assert languages.check_target(" ZH-cn ") == "zh-CN"
    assert languages.check_source(None) == "auto" and languages.check_source("") == "auto"
    assert languages.check_source("AUTO") == "auto"
    for bad in ("xx", "english", "zh", "../en", None):
        with pytest.raises(ValueError):
            languages.check_target(bad)
    with pytest.raises(ValueError):
        languages.check_mode("both")


def test_sample_pages_edges():
    assert languages.sample_pages([]) == []
    assert languages.sample_pages(["", "  ", None]) == []
    pages = [f"page {n}" for n in range(100)]
    got = languages.sample_pages(pages, 12)
    assert len(got) == 12 and got[0] == "page 0" and got[-1] != "page 11"   # spread over the book


@pytest.mark.parametrize("text,expected", [("", False), ("12 34", False), ("a", False), ("ab", True),
                                           ("字", True), ("あ", True), ("한", True), ("1 - 2 ©", False)])
def test_has_words(text, expected):
    assert languages.has_words(text) is expected


def test_page_label_for_unknown_language_falls_back():
    assert languages.page_label("auto", 4) == "Page 4"
    assert languages.native_name("auto") == "Original"
    assert languages.is_rtl("auto") is False


# ---- output names ----------------------------------------------------------------------------

def test_default_output_names(tmp_path):
    from booktrans.pipeline import default_output, glossary_path
    b = tmp_path / "My Book.v2.pdf"
    assert default_output(b).name == "My Book.v2_bilingual.pdf"
    assert default_output(b, "1 - 5").name == "My Book.v2_bilingual pages 1-5.pdf"
    assert default_output(b, mode="target-only", target="en").name == "My Book.v2_en.pdf"
    assert glossary_path(tmp_path / "o.pdf", "zh-CN").name == "o.glossary.json"
    assert glossary_path(tmp_path / "o.pdf", "ja").name == "o.glossary.ja.json"


# ---- the pipeline end to end on degenerate books -------------------------------------------------

def test_empty_book_is_an_error_not_an_empty_pdf(tmp_path):
    from booktrans.pipeline import translate_book
    (tmp_path / "e.txt").write_text("")
    with pytest.raises(ValueError):
        translate_book(tmp_path / "e.txt", tmp_path / "o.pdf", FakeBackend())
    assert not (tmp_path / "o.pdf").exists()


@pytest.mark.parametrize("pages", ["9", "0", "50-60"])
def test_page_range_outside_the_book_is_an_error(tmp_path, pages):
    from booktrans.pipeline import translate_book
    (tmp_path / "b.txt").write_text("Hello there, this is a short book.")
    with pytest.raises(ValueError):
        translate_book(tmp_path / "b.txt", tmp_path / "o.pdf", FakeBackend(), pages=pages)


def test_bad_languages_and_modes_are_rejected_before_any_work(tmp_path):
    from booktrans.pipeline import translate_book
    (tmp_path / "b.txt").write_text("Hello there, this is a short book.")
    fb = FakeBackend()
    for kw in ({"target": "xx"}, {"source": "xx"}, {"output_mode": "x"}):
        with pytest.raises(ValueError):
            translate_book(tmp_path / "b.txt", tmp_path / "o.pdf", fb, **kw)
    assert fb.calls == []


def test_only_cached_with_nothing_cached_is_an_error(tmp_path):
    from booktrans.pipeline import translate_book
    (tmp_path / "b.txt").write_text("Hello there, this is a short book.")
    with pytest.raises(ValueError):
        translate_book(tmp_path / "b.txt", tmp_path / "o.pdf", FakeBackend(), only_cached=True)


def test_resume_after_a_failure_pays_only_for_the_missing_pages(tmp_path, no_sleep):
    from booktrans.pipeline import translate_book
    body = "\n\n".join("Paragraph %d. " % n + "word " * 60 for n in range(30))
    (tmp_path / "b.txt").write_text(body)
    pages = len(readers.read_txt(tmp_path / "b.txt"))
    assert pages >= 3
    state = {"n": 0, "fail": True}

    def reply(user):
        state["n"] += 1
        if state["fail"] and state["n"] >= 3:   # stays down, so every retry fails too
            raise BackendError("down")
        return "译:" + user[:5]
    with pytest.raises(BackendError):
        translate_book(tmp_path / "b.txt", tmp_path / "o.pdf", FakeBackend(reply=reply),
                       auto_glossary=False, source="en")
    state.update(fail=False, n=0)
    fb = FakeBackend(reply=reply)
    translate_book(tmp_path / "b.txt", tmp_path / "o.pdf", fb, auto_glossary=False, source="en")
    assert 0 < len(fb.calls) < pages                          # the pages done before the failure were kept


def test_switching_the_target_does_not_reuse_the_other_targets_pages(tmp_path):
    from booktrans.pipeline import translate_book
    (tmp_path / "b.txt").write_text("Hello there, this is a short book.")
    out, fb = tmp_path / "o.pdf", FakeBackend()
    translate_book(tmp_path / "b.txt", out, fb, auto_glossary=False, source="en", target="fr")
    n = len(fb.calls)
    translate_book(tmp_path / "b.txt", out, fb, auto_glossary=False, source="en", target="fr")
    assert len(fb.calls) == n                                  # same target: all cached
    translate_book(tmp_path / "b.txt", out, fb, auto_glossary=False, source="en", target="de")
    assert len(fb.calls) == n + 1                              # another target: translated again


# ---- the PDF writer --------------------------------------------------------------------------------

def test_text_pages_degenerate_text():
    import fitz
    from booktrans.writer import text_pages
    for text in ("", "   ", "\n\n\n\n", "a" * 30000, "word " * 6000, "😀" * 200, "‮" * 50,
                 "<b>&amp; <script>", "مرحبا بالعالم " * 50, "你好" * 3000):
        data = text_pages(text, "Label", "ar" if "مرحبا" in text else "en")
        with fitz.open("pdf", data) as doc:
            assert doc.page_count >= 1


def test_text_pages_markup_in_text_is_shown_not_interpreted():
    import fitz
    from booktrans.writer import text_pages
    with fitz.open("pdf", text_pages("<b>bold</b> & more", "L", "en")) as doc:
        assert "<b>bold</b> & more" in doc[0].get_text()


def test_make_pdf_with_no_pages_writes_a_valid_empty_file(tmp_path):
    from booktrans.writer import make_pdf
    make_pdf([], [], tmp_path / "o.pdf")
    assert (tmp_path / "o.pdf").stat().st_size > 0


def test_make_pdf_blank_translation_becomes_a_dash_page(tmp_path):
    import fitz
    from booktrans.writer import make_pdf
    make_pdf(["src one", "src two"], ["", ""], tmp_path / "o.pdf", mode="target-only")
    with fitz.open(tmp_path / "o.pdf") as doc:
        assert doc.page_count == 2 and "—" in doc[1].get_text()


def test_make_pdf_cover_only_book_bilingual_and_target_only(tmp_path, text_pdf):
    import fitz
    from booktrans.writer import make_pdf
    make_pdf(["a"], [""], tmp_path / "b.pdf", text_pdf)
    make_pdf(["a"], [""], tmp_path / "t.pdf", text_pdf, mode="target-only")
    with fitz.open(tmp_path / "b.pdf") as b, fitz.open(tmp_path / "t.pdf") as t:
        assert b.page_count == 1 and t.page_count == 1


# ---- job store and failure reporting ---------------------------------------------------------------

def test_job_store_rejects_unsafe_ids(tmp_path):
    from booktrans.web.jobs import JobStore
    s = JobStore(tmp_path / "jobs")
    jid = s.new("a.pdf")
    for bad in ("../" + jid, jid + "/", jid[:-1], jid + "x", "", None, 5, ["x"], "a" * 22 + "\n", "..", "."):
        assert s.dir(bad) is None and s.read(bad) is None
    s.delete("../../etc")                                      # must not raise or leave the store
    assert s.dir(jid) is not None


def test_job_store_filename_sanitising(tmp_path):
    from booktrans.web.jobs import JobStore
    s = JobStore(tmp_path / "jobs")
    for name, safe in (("../../etc/passwd.pdf", "passwd.pdf"), ("a<b>:c?.txt", "a_b__c_.txt"), ("", ""),
                       ("x" * 500 + ".pdf", None)):
        job = s.read(s.new(name))
        assert "/" not in job["filename"] and "\\" not in job["filename"] and len(job["filename"]) <= 120
        if safe is not None:
            assert job["filename"] == safe
    kept = JobStore(tmp_path / "k", keep_names=True)
    assert kept.read(kept.new("书名 (第二版).pdf"))["filename"] == "书名 (第二版).pdf"
    assert kept.read(kept.new("../../evil.txt"))["filename"] == "evil.txt"


def test_job_store_damaged_job_json_reads_as_missing(tmp_path):
    from booktrans.web.jobs import JobStore
    s = JobStore(tmp_path / "jobs")
    jid = s.new("a.pdf")
    (s.dir(jid) / "job.json").write_text("{broken")
    assert s.read(jid) is None
    (s.dir(jid) / "job.json").write_text("[1]")
    assert s.read(jid) is None                                 # never a list, never an exception


def test_job_store_cleanup_and_reset_ignore_strays(tmp_path):
    from booktrans.web.jobs import JobStore
    s = JobStore(tmp_path / "jobs")
    (s.root / "stray.txt").write_text("x")
    (s.root / "not-a-job-id").mkdir()
    jid = s.new("a.pdf")
    s.write(jid, state="running")
    assert s.reset_interrupted() == 1 and s.read(jid)["state"] == "paused"
    assert s.cleanup(-1) == 1                                  # only the real job is swept
    assert (s.root / "stray.txt").exists() and (s.root / "not-a-job-id").exists()


def test_failure_info_hides_the_api_key_everywhere():
    from booktrans.web.jobs import failure_info
    key = "sk-secret-123456"
    for exc in (BackendError(f"bad key {key}"), ValueError(f"{key} is wrong"), RuntimeError(key),
                OSError(5, f"disk {key}")):
        code, detail, text = failure_info(exc, key)
        assert key not in detail and key not in text


def test_failure_info_classification():
    from booktrans.web.jobs import failure_info
    assert failure_info(AuthError("x"), "")[0] == "auth"
    assert failure_info(BackendError("credit balance is too low"), "")[0] == "quota"
    assert failure_info(BackendError("timed out"), "")[0] == "timeout"
    assert failure_info(ValueError("bad range"), "")[0] == "input"
    assert failure_info(MemoryError(), "")[0] == "memory"
    assert failure_info(RuntimeError("x"), "")[0] == "unknown"
    assert failure_info(Exception(), None)[0] == "unknown"
    assert len(failure_info(BackendError("x" * 5000), "")[1]) <= 400


def test_preview_range_edges():
    from booktrans.web.jobs import preview_range
    assert preview_range("", 10) == "1-3"
    assert preview_range("", 2) == "1-2"
    assert preview_range("5-9", 10) == "5-7"
    with pytest.raises(IndexError):
        preview_range("20", 10)                                # empty selection: the caller checks first


# ---- command line --------------------------------------------------------------------------------------

@pytest.mark.parametrize("value", ["-1", "nan", "inf", "abc"])
def test_cli_rejects_a_senseless_spend_limit(monkeypatch, tmp_path, value, capsys):
    from booktrans import cli
    (tmp_path / "b.txt").write_text("Hello there, this is a short book.")
    monkeypatch.setattr("sys.argv", ["booktrans", str(tmp_path / "b.txt"), "--max-spend", value])
    monkeypatch.setattr(cli, "make_backend", lambda *a, **k: pytest.fail("must stop before any backend"))
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert e.value.code not in (0, None)


@pytest.mark.parametrize("flag,value", [("--target", "xx"), ("--source", "xx"), ("--output-mode", "x"),
                                        ("--pages", "a"), ("--backend", "nope")])
def test_cli_rejects_bad_options(monkeypatch, tmp_path, flag, value):
    from booktrans import cli
    (tmp_path / "b.txt").write_text("Hello there, this is a short book.")
    monkeypatch.setattr("sys.argv", ["booktrans", str(tmp_path / "b.txt"), flag, value])
    monkeypatch.setattr(cli, "make_backend", lambda *a, **k: FakeBackend())
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert e.value.code not in (0, None)


def test_cli_missing_book_is_a_clean_exit(monkeypatch, tmp_path):
    from booktrans import cli
    monkeypatch.setattr("sys.argv", ["booktrans", str(tmp_path / "nope.txt")])
    monkeypatch.setattr(cli, "make_backend", lambda *a, **k: FakeBackend())
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert e.value.code not in (0, None)


# ---- the claude command-line backend ---------------------------------------------------------------

def _cli(monkeypatch, run):
    from booktrans.backends import claude_cli
    monkeypatch.setattr(claude_cli.subprocess, "run", run)
    return claude_cli.ClaudeCLIBackend()


class _Done:
    def __init__(self, out="", code=0, err=""):
        self.stdout, self.returncode, self.stderr = out, code, err


def test_claude_cli_reads_utf8_whatever_the_locale(monkeypatch):
    seen = {}

    def run(cmd, **kw):
        seen.update(kw)
        return _Done(json.dumps({"result": " 你好 ", "usage": {"input_tokens": 1}}))
    assert _cli(monkeypatch, run).complete("s", "u") == "你好"
    assert seen["encoding"] == "utf-8" and seen["timeout"] > 0


def test_claude_cli_missing_binary_is_a_readable_error_not_a_traceback(monkeypatch):
    def run(cmd, **kw):
        raise FileNotFoundError("claude")
    with pytest.raises(ValueError, match="claude command was not found"):
        _cli(monkeypatch, run).complete("s", "u")


def test_claude_cli_timeout_is_a_backend_error(monkeypatch):
    import subprocess

    def run(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 1)
    with pytest.raises(BackendError):
        _cli(monkeypatch, run).complete("s", "u")


@pytest.mark.parametrize("out,code", [("", 1), ("not json", 0), ('{"is_error": true, "result": "x"}', 0),
                                      ("null", 0), ("[]", 0)])
def test_claude_cli_failures_are_backend_errors(monkeypatch, out, code):
    with pytest.raises(BackendError):
        _cli(monkeypatch, lambda cmd, **kw: _Done(out, code)).complete("s", "u")


def test_claude_cli_null_result_is_an_empty_string(monkeypatch):
    assert _cli(monkeypatch, lambda cmd, **kw: _Done('{"result": null}')).complete("s", "u") == ""


def test_paginate_cuts_chinese_text_at_sentence_ends():
    para = "".join(f"这是第{n}个句子，它很短。" for n in range(400))
    pages = readers.paginate([para])
    assert len(pages) > 1 and all(len(p) <= readers.CHARS_PER_PAGE for p in pages)
    assert all(p.endswith("。") for p in pages) and "".join(pages) == para


def test_a_bad_glossary_file_fails_before_anything_is_paid_for(tmp_path):
    from booktrans.pipeline import translate_book
    (tmp_path / "b.txt").write_text("Hello there, this is a short book.")
    (tmp_path / "g.txt").write_bytes(b"Boyle=\xff\xfe")
    fb = FakeBackend()
    with pytest.raises(ValueError):
        translate_book(tmp_path / "b.txt", tmp_path / "o.pdf", fb, glossary_file=tmp_path / "g.txt")
    assert fb.calls == []


def test_glossary_file_entries_override_the_automatic_ones(tmp_path):
    from booktrans.pipeline import translate_book
    (tmp_path / "b.txt").write_text("Boyle met Boyle. Boyle spoke again to Boyle here.")
    (tmp_path / "g.txt").write_text("Boyle=波义耳", encoding="utf-8")
    fb = FakeBackend()
    translate_book(tmp_path / "b.txt", tmp_path / "o.pdf", fb, glossary_file=tmp_path / "g.txt", source="en")
    assert any("Boyle = 波义耳" in c or "Boyle" in c for c in fb.calls)
    assert read_json(tmp_path / "o.glossary.json")["Boyle"] == "波义耳"


def test_cli_missing_glossary_file_is_a_clean_exit(monkeypatch, tmp_path):
    from booktrans import cli
    (tmp_path / "b.txt").write_text("Hello there, this is a short book.")
    monkeypatch.setattr("sys.argv", ["booktrans", str(tmp_path / "b.txt"), "--glossary", str(tmp_path / "no.txt")])
    monkeypatch.setattr(cli, "make_backend", lambda *a, **k: pytest.fail("must stop before any backend"))
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert "glossary" in str(e.value.code)
