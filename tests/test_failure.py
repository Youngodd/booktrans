"""When something goes wrong: a classified message that says what was being done and what to do, retry
notices, the provider's reason, keys blanked out, a log file for the details, and no swallowed failure
that costs the user something (docs: booktrans/failure.py)."""
import os
from pathlib import Path

import pytest

from booktrans import cli, failure
from booktrans.backends import base
from booktrans.backends.base import AuthError, BackendError
from tests.conftest import FakeBackend

KEY = "sk-secret-abcdefghijklmnop1234"


@pytest.fixture
def no_sleep(monkeypatch):
    slept = []
    monkeypatch.setattr(base.time, "sleep", slept.append)
    return slept


@pytest.fixture
def go(monkeypatch, tmp_path):
    """Run the command line with a chosen backend; returns (exit text or None, exit code)."""
    backend = {"b": FakeBackend()}
    monkeypatch.setattr(cli, "make_backend", lambda *a, **k: backend["b"])
    monkeypatch.setattr("sys.stdin", type("S", (), {"isatty": lambda self: False})())

    def run(*argv, book="book.md", text="# Title\n\nHello there, this is a short book to translate.\n", using=None):
        if using is not None:
            backend["b"] = using
        path = tmp_path / book
        if not path.exists():
            path.write_text(text, encoding="utf-8")
        monkeypatch.setattr("sys.argv", ["booktrans", str(path), "--backend", "api", "--no-auto-glossary", *argv])
        try:
            cli.main()
        except SystemExit as e:
            return (str(e.code) if e.code not in (0, None) else None), (1 if isinstance(e.code, str) else e.code)
        return None, 0
    run.dir = tmp_path
    return run


def log_text():
    return failure.log_path().read_text(encoding="utf-8")


# ---------------------------------------------------------------- the command line never ends in a bare traceback

def test_an_unexpected_error_gives_one_classified_message_and_a_log_file(go, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError(f"something nobody expected, with {KEY} in it")
    monkeypatch.setattr(cli, "translate_book", boom)
    said, code = go()
    assert code == 1 and said.startswith("Error:") and "RuntimeError" in said
    assert "log file has the full details" in said and f"Details: {failure.log_path()}" in said
    assert "Traceback" not in said and KEY not in said
    log = log_text()
    assert "Traceback" in log and "RuntimeError" in log and KEY not in log and "booktrans" in log


def test_debug_adds_the_full_traceback_to_the_message(go, monkeypatch):
    monkeypatch.setattr(cli, "translate_book", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("deep failure")))
    plain, _ = go()
    debug, _ = go("--debug")
    assert "Traceback" not in plain and "Traceback" in debug and "deep failure" in debug


@pytest.mark.parametrize("exc,words", [
    (OSError(28, "No space left on device"), "disk"),
    (MemoryError(), "memory"),
    (ConnectionError("Connection reset"), "internet connection"),
    (KeyError("k"), "unexpected"),
])
def test_other_kinds_of_failure_say_what_to_do(go, monkeypatch, exc, words):
    monkeypatch.setattr(cli, "translate_book", lambda *a, **k: (_ for _ in ()).throw(exc))
    said, code = go()
    assert code == 1 and words in said.lower() and "Details:" in said


def test_a_book_that_cannot_be_read_gives_the_reason_and_still_writes_the_log(go):
    (go.dir / "bad.docx").write_bytes(b"not a zip at all")
    said, code = go(book="bad.docx")
    assert code == 1 and ".docx" in said and "damaged" in said and "Traceback" not in said
    assert "bad.docx" in log_text() or "docx" in log_text()


def test_a_missing_book_and_a_bad_option_are_plain_messages(go):
    said, code = go("--pages", "zzz")
    assert code == 1 and "Invalid page range" in said


def test_interrupting_with_ctrl_c_says_progress_is_saved_and_exits_130(go, monkeypatch, capsys):
    monkeypatch.setattr(cli, "translate_book", lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()))
    said, code = go()
    assert code == 130 and "Progress is saved" in capsys.readouterr().err


def test_the_spend_limit_exit_code_is_unchanged(go):
    from tests.conftest import PricedBackend
    book = "\n\n".join(f"Paragraph {i}. " + "word " * 300 for i in range(6))
    said, code = go("--max-spend", "1.5", book="long.md", text=book, using=PricedBackend())
    assert code == cli.EXIT_SPEND_LIMIT


# ---------------------------------------------------------------- a failing model call: what, where, how often, why

class Down(FakeBackend):
    provider, model = "qwen", "qwen3.7-plus"

    def __init__(self, error):
        super().__init__(reply=lambda u: (_ for _ in ()).throw(error))
        self.model = "qwen3.7-plus"


def test_retry_notices_name_the_page_the_attempt_the_cause_and_the_wait(no_sleep, capsys):
    with pytest.raises(BackendError):
        with failure.working_on(stage="translate", page=12):
            base.complete(Down(BackendError("Error code: 429 rate limit reached")), "s", "t", 100)
    err = capsys.readouterr().err.splitlines()
    assert err == ["While translating page 12: attempt 1/4 failed (rate limit); retrying in 5s",
                   "While translating page 12: attempt 2/4 failed (rate limit); retrying in 20s",
                   "While translating page 12: attempt 3/4 failed (rate limit); retrying in 60s"]


def test_retry_notices_without_a_task_still_make_sense(no_sleep, capsys):
    with pytest.raises(BackendError):
        base.complete(Down(BackendError("request timed out")), "s", "t", 100)
    assert capsys.readouterr().err.splitlines()[0] == "Attempt 1/4 failed (timed out); retrying in 5s"


def test_giving_up_names_the_task_the_backend_the_model_the_attempts_and_the_cause(no_sleep, capsys):
    cause = BackendError("Connection error")
    with pytest.raises(BackendError) as e:
        with failure.working_on(stage="translate", page=7):
            base.complete(Down(cause), "s", "t", 100)
    text = str(e.value)
    assert text.startswith("Translating page 7: qwen (qwen3.7-plus) failed after 4 attempts (network error): ")
    assert "Connection error" in text and e.value.__cause__ is cause  # the original is kept


def test_a_refused_key_is_not_retried_and_says_which_model_was_refused(no_sleep, capsys):
    with pytest.raises(AuthError) as e:
        with failure.working_on(stage="ocr", page=3):
            base.complete(Down(AuthError("The provider refused the call (bad key)")), "s", "t", 100)
    assert no_sleep == [] and "Reading (OCR) page 3" in str(e.value) and "qwen (qwen3.7-plus)" in str(e.value)
    assert capsys.readouterr().err == ""


def test_a_failing_run_from_the_command_line_names_the_part_backend_model_and_the_resume_hint(go, no_sleep, capsys):
    said, code = go(using=Down(BackendError("Connection error")))
    err = capsys.readouterr().err
    assert code == 1
    assert "Error: Translating part 1: qwen (qwen3.7-plus) failed after 4 attempts (network error)" in said
    assert "Book: book.md" in said and "internet connection" in said
    assert "Progress is saved; run the same command again to resume." in said and "Details:" in said
    assert "attempt 1/4 failed (network error); retrying in 5s" in err


def test_the_task_is_kept_on_the_error_when_it_leaves_the_block():
    with pytest.raises(RuntimeError) as e:
        with failure.working_on(stage="translate", page=5):
            with failure.working_on(stage="glossary"):
                raise RuntimeError("x")
    assert failure.task_of(e.value) == "collecting names page 5"
    assert failure.where() == ""  # and nothing is left behind


def test_the_input_file_stage_names_are_used_for_reading_and_writing(tmp_path, monkeypatch):
    from booktrans.options import JobOptions
    from booktrans import pipeline
    book = tmp_path / "b.md"
    book.write_text("# T\n\nSome text here to translate.\n")
    monkeypatch.setattr(pipeline, "write_blocks", lambda *a, **k: (_ for _ in ()).throw(OSError(28, "No space left on device")))
    with pytest.raises(OSError) as e:
        pipeline.translate_book(book, tmp_path / "o.md", FakeBackend(), JobOptions(output_format="md", auto_glossary=False))
    assert failure.task_of(e.value) == "writing the output file"
    assert failure.classify(e.value) == "disk"


# ---------------------------------------------------------------- the provider's reason

def test_the_anthropic_backend_gives_the_providers_reason_and_the_model():
    import anthropic
    import httpx
    from booktrans.backends.anthropic_api import AnthropicBackend
    resp = httpx.Response(401, request=httpx.Request("POST", "http://x"))
    err = anthropic.AuthenticationError("Invalid API key for this organisation", response=resp, body=None)
    b = AnthropicBackend(api_key="k")

    class Client:
        class messages:
            @staticmethod
            def create(**kw):
                raise err
    b.client = Client
    with pytest.raises(AuthError) as e:
        b.complete("s", "t")
    text = str(e.value)
    assert "claude-sonnet-5-5" in text and "Invalid API key for this organisation" in text and "credit" in text


def test_the_openai_compatible_backend_names_provider_and_model_in_a_failure():
    import openai
    import httpx
    from booktrans.backends.openai_compat import OpenAICompatBackend
    b = OpenAICompatBackend(provider="qwen", api_key="k")

    class Chat:
        class completions:
            @staticmethod
            def create(**kw):
                raise openai.APIConnectionError(request=httpx.Request("POST", "http://x"))
    b.client = type("C", (), {"chat": Chat})
    with pytest.raises(BackendError) as e:
        b.complete("s", "t")
    assert "qwen" in str(e.value) and "qwen3.7-plus" in str(e.value)


# ---------------------------------------------------------------- keys never reach a message or the log

@pytest.mark.parametrize("text", [f"bad key {KEY} here", f"{KEY}", f"a {KEY} b {KEY} c", "sk-ant-api03-abcdefghijklmnopqrstu",
                                  "key-0123456789abcdefgh", "api_abcdefghijklmnopqrst"])
def test_redact_blanks_anything_shaped_like_a_key_and_the_given_secret(text):
    out = failure.redact(text, (KEY,))
    assert KEY not in out and "abcdefghijklmnop" not in out and "***" in out


def test_redact_knows_the_keys_in_the_environment(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "plainsecretvalue99")
    assert "plainsecretvalue99" not in failure.redact("failed with plainsecretvalue99 inside")


def test_redact_leaves_ordinary_text_alone():
    text = "Translating page 12: qwen (qwen3.7-plus) failed after 4 attempts (network error): sk-"
    assert failure.redact(text) == text


def test_a_key_in_the_environment_never_reaches_the_screen_or_the_log(go, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "envkey-9999-secret-value")
    monkeypatch.setattr(cli, "translate_book", lambda *a, **k: (_ for _ in ()).throw(
        BackendError("Error 401: bad key envkey-9999-secret-value")))
    said, _ = go("--debug")
    assert "envkey-9999-secret-value" not in said and "envkey-9999-secret-value" not in log_text()


def test_the_web_service_still_hides_the_message_of_unexpected_errors():
    from booktrans.web.jobs import failure_info
    code, detail, text = failure_info(RuntimeError("opened /srv/private/data/jobs/x.json"), "")
    assert detail == "RuntimeError" and "/srv" not in text
    assert failure_info(OSError(2, "No such file", "/srv/private/x"), "")[1] == "No such file"


# ---------------------------------------------------------------- the log file

def test_the_log_is_cut_when_it_grows_past_a_megabyte(monkeypatch):
    path = failure.log_path()
    path.write_text("x" * (failure.MAX_LOG_BYTES + 10))
    assert failure.write_log("fresh") == path
    assert path.read_text(encoding="utf-8").count("fresh") == 1 and path.stat().st_size < 1000


def test_a_log_that_cannot_be_written_does_not_make_things_worse(monkeypatch, tmp_path):
    (tmp_path / "afile").write_text("x")
    monkeypatch.setenv("BOOKTRANS_LOG", str(tmp_path / "afile" / "error.log"))
    assert failure.write_log("x") is None
    text = failure.report(RuntimeError("boom"))
    assert "could not be written" in text and "--debug" in text


def test_the_default_log_is_in_the_home_folder(monkeypatch):
    monkeypatch.delenv("BOOKTRANS_LOG")
    assert failure.log_path() == Path.home() / ".booktrans" / "error.log"


# ---------------------------------------------------------------- a swallowed failure is said or logged

def test_a_damaged_cache_is_said_not_silently_ignored(tmp_path, capsys):
    from booktrans.fsutil import read_json
    (tmp_path / "o.cache.json").write_text("{not json")
    assert read_json(tmp_path / "o.cache.json") == {}
    assert "o.cache.json could not be read" in capsys.readouterr().err
    assert "o.cache.json" in log_text()


def test_a_missing_cache_is_normal_and_silent(tmp_path, capsys):
    from booktrans.fsutil import read_json
    assert read_json(tmp_path / "none.json") == {}
    assert capsys.readouterr().err == ""


def test_a_damaged_spend_file_says_the_count_starts_again(tmp_path, capsys):
    from booktrans.spend import Meter
    (tmp_path / "o.spend.json").write_text("garbage")
    assert Meter(5, tmp_path / "o.spend.json").spent == 0.0
    assert "counting starts again from zero" in capsys.readouterr().err


def test_a_damaged_usage_log_says_earlier_runs_are_dropped(tmp_path, capsys):
    from booktrans.usage import Usage
    (tmp_path / "o.usage.json").write_text("garbage")
    usage = Usage()
    usage.record({"input_tokens": 5, "output_tokens": 5})
    usage.report(tmp_path / "o.pdf")
    assert "earlier runs are dropped" in capsys.readouterr().err


def test_names_that_could_not_be_collected_are_reported_not_skipped_silently(tmp_path, no_sleep, capsys):
    from booktrans import glossary
    pages = ["Boyle met Hooke in London. Boyle wrote to Hooke. Hooke wrote to Boyle. " * 4] * 3
    glossary.build(Down(BackendError("Connection error")), pages, pages, {}, None, "en", "zh-CN")
    err = capsys.readouterr().err
    assert "names could not be collected" in err and "Connection error" in err


def test_a_picture_word_cannot_hold_is_reported(tmp_path, capsys):
    from booktrans.blockwriters import write_blocks
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "x.svg").write_bytes(b"<svg/>")
    write_blocks([{"type": "figure", "image": "x.svg", "alt": "a drawing"}], tmp_path / "assets", tmp_path / "o.docx",
                 "docx", bilingual=True, lang="zh-CN", title="T")
    assert "x.svg could not be put in the Word file" in capsys.readouterr().err


def test_a_picture_that_cannot_be_read_from_a_pdf_is_reported_and_the_rest_is_written(tmp_path, capsys, monkeypatch):
    import fitz
    from booktrans.options import JobOptions
    from booktrans.pipeline import translate_book
    d = fitz.open()
    p = d.new_page()
    p.insert_text((72, 60), "A heading line of text above the picture, long enough.")
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 100, 100), False)
    pix.set_rect(pix.irect, (1, 2, 3))
    p.insert_image(fitz.Rect(50, 100, 250, 300), stream=pix.tobytes("png"))
    d.save(tmp_path / "p.pdf")

    def broken(*a, **k):
        raise RuntimeError("bad image")
    translate_book(tmp_path / "p.pdf", tmp_path / "ok.md", FakeBackend(), JobOptions(output_format="md", auto_glossary=False))
    real = fitz.Pixmap
    monkeypatch.setattr(fitz, "Pixmap", broken)
    try:
        translate_book(tmp_path / "p.pdf", tmp_path / "o.md", FakeBackend(), JobOptions(output_format="md", auto_glossary=False,
                                                                                         state=tmp_path / "other.md"))
    finally:
        monkeypatch.setattr(fitz, "Pixmap", real)
    assert "a picture on page 1 could not be read (RuntimeError)" in capsys.readouterr().err
    assert "heading line" in (tmp_path / "o.md").read_text(encoding="utf-8")
