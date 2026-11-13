"""JobOptions: one definition of a job's settings, and what each entry point fills in."""
import dataclasses
from pathlib import Path

import pytest

import booktrans.pipeline as pipeline
import booktrans.web.jobs as jobs
from booktrans import cli
from booktrans.fsutil import read_json
from booktrans.options import JobOptions
from tests.conftest import FakeBackend


# ---- the settings and their checking ---------------------------------------------------------------

def test_the_defaults_are_the_ones_translate_book_always_had():
    assert dataclasses.asdict(JobOptions()) == {
        "pages": None, "redo": None, "flat": False, "glossary_file": None, "auto_glossary": True,
        "only_cached": False, "refresh_glossary": False, "source": "auto", "target": "zh-CN",
        "output_mode": "bilingual", "state": None}


def test_values_are_normalised_and_checked_when_the_options_are_made():
    o = JobOptions(source=None, target=" EN ", state="out.pdf", glossary_file="g.txt")
    assert (o.source, o.target) == ("auto", "en")
    assert o.state == Path("out.pdf") and o.glossary_file == Path("g.txt")
    for bad in ({"target": "xx"}, {"source": "xx"}, {"output_mode": "both"},
                {"only_cached": True, "refresh_glossary": True}):
        with pytest.raises(ValueError):
            JobOptions(**bad)


def test_options_cannot_be_changed_but_can_be_copied_with_changes():
    o = JobOptions(target="fr")
    with pytest.raises(dataclasses.FrozenInstanceError):
        o.target = "de"
    assert dataclasses.replace(o, flat=True).target == "fr"


def test_every_setting_is_documented_in_translate_book():
    doc = pipeline.translate_book.__doc__
    for f in dataclasses.fields(JobOptions):
        assert f.name in doc, f.name


# ---- translate_book takes either form ----------------------------------------------------------------

def book(tmp_path):
    (tmp_path / "b.txt").write_text("Hello there, this is a short book.", encoding="utf-8")
    return tmp_path / "b.txt", tmp_path / "o.pdf"


def test_options_and_keyword_settings_do_the_same_work(tmp_path):
    b, out = book(tmp_path)
    one, two = FakeBackend(), FakeBackend()
    pipeline.translate_book(b, tmp_path / "x.pdf", one, JobOptions(target="fr", output_mode="target-only", auto_glossary=False))
    pipeline.translate_book(b, tmp_path / "y.pdf", two, target="fr", output_mode="target-only", auto_glossary=False)
    assert one.calls == two.calls
    assert read_json(tmp_path / "x.cache.json") == read_json(tmp_path / "y.cache.json") != {}


def test_both_forms_at_once_or_an_unknown_setting_is_refused(tmp_path):
    b, out = book(tmp_path)
    with pytest.raises(TypeError):
        pipeline.translate_book(b, out, FakeBackend(), JobOptions(), target="fr")
    with pytest.raises(TypeError):
        pipeline.translate_book(b, out, FakeBackend(), colour="red")
    with pytest.raises(ValueError):
        pipeline.translate_book(b, out, FakeBackend(), target="xx")


# ---- what the entry points fill in -----------------------------------------------------------------------

class Run:
    """Captures what an entry point hands to translate_book."""

    def __init__(self):
        self.calls = []

    def __call__(self, book, out, translator, options=None, **kw):
        self.calls.append((Path(book).name, Path(out).name, options, kw))
        return out


@pytest.fixture
def cli_run(monkeypatch, tmp_path):
    (tmp_path / "b.txt").write_text("Hello there, this is a short book.\n\n" * 3, encoding="utf-8")
    (tmp_path / "g.txt").write_text("A=b", encoding="utf-8")
    run = Run()

    class Vision(FakeBackend):
        supports_vision = True
    monkeypatch.setattr(cli, "translate_book", run)
    monkeypatch.setattr(cli, "make_backend", lambda *a, **k: Vision())
    monkeypatch.setattr(cli, "glossary_changes", lambda *a, **k: {"pages": [1], "translated": 2})
    monkeypatch.setattr("sys.stdin", type("S", (), {"isatty": lambda self: False})())

    def go(*argv):
        monkeypatch.setattr("sys.argv", ["booktrans", str(tmp_path / "b.txt"), "--backend", "api", *argv])
        run.calls.clear()
        cli.main()
        return run.calls
    go.dir = tmp_path
    return go


def test_cli_plain_run(cli_run):
    ((name, out, o, kw),) = cli_run("--max-spend", "0")
    assert (name, out) == ("b.txt", "b_bilingual.pdf")
    assert o == JobOptions(state=cli_run.dir / "b_bilingual.pdf")
    assert kw["meter"] is not None and kw["progress"] is not None and kw["ocr_backend"] is None


def test_cli_every_option(cli_run):
    g = cli_run.dir / "g.txt"
    ((_, out, o, kw),) = cli_run("--max-spend", "0", "--pages", "1-1", "--redo", "1", "--flat", "--glossary", str(g),
                                 "--no-auto-glossary", "--target", "en", "--source", "fr", "--output-mode", "target-only",
                                 "-o", str(cli_run.dir / "x.pdf"), "--ocr")
    assert o == JobOptions(pages="1-1", redo="1", flat=True, glossary_file=g, auto_glossary=False, source="fr",
                           target="en", output_mode="target-only", state=cli_run.dir / "x.pdf")
    assert kw["ocr_backend"] is not None


def test_cli_finish_partial_spends_nothing_and_ignores_the_other_settings(cli_run):
    ((_, _, o, kw),) = cli_run("--finish-partial", "--target", "ja", "--redo", "1",
                               "--glossary", str(cli_run.dir / "g.txt"), "--no-auto-glossary")
    assert o.only_cached and o.target == "ja"
    assert (o.redo, o.glossary_file, o.auto_glossary, o.refresh_glossary) == (None, None, True, False)
    assert "meter" not in kw


def test_cli_apply_glossary_asks_for_a_refresh(cli_run):
    ((_, _, o, _),) = cli_run("--max-spend", "0", "--apply-glossary")
    assert o.refresh_glossary and not o.only_cached


def test_cli_stopping_at_the_limit_then_finishing_uses_the_cached_pages_only(cli_run, monkeypatch):
    from booktrans.spend import SpendLimitReached
    seen = []

    def run(book, out, translator, options=None, **kw):
        seen.append(options)
        if not options.only_cached:
            raise SpendLimitReached(1.0, 1.0)
        return out
    monkeypatch.setattr(cli, "translate_book", run)
    monkeypatch.setattr(cli, "decide", lambda e, last, out: ("finish",))
    monkeypatch.setattr("sys.argv", ["booktrans", str(cli_run.dir / "b.txt"), "--backend", "api", "--target", "de"])
    cli.main()
    assert [o.only_cached for o in seen] == [False, True] and seen[1].target == "de"


@pytest.fixture
def job_run(monkeypatch, tmp_path):
    run = Run()
    monkeypatch.setattr(pipeline, "translate_book", run)

    def go(**fields):
        store = jobs.JobStore(tmp_path / f"jobs{len(run.calls)}{len(fields)}")
        jid = store.new("My Book.txt", **{"ocr": False, "range": "1-3", "pages_total": 3, **fields})
        (store.dir(jid) / "input.txt").write_text("x")
        run.calls.clear()
        jobs.run_job(str(store.root), jid, "sk-test-12345678", lambda key, provider="api", **kw: FakeBackend(), "api")
        return run.calls
    return go


def test_a_job_made_before_the_language_settings_existed_gets_the_defaults(job_run):
    ((name, out, o, kw),) = job_run()
    assert (name, out) == ("input.txt", "output.pdf")
    assert o == JobOptions(pages="1-3")
    assert kw["meter"] is not None and kw["progress"] is not None and kw["ocr_backend"] is None


def test_a_job_with_every_setting(job_run):
    ((_, _, o, kw),) = job_run(ocr=True, auto_glossary=False, source="fr", target="ja", output_mode="target-only",
                               refresh_glossary=True, spend_limit=5, model="m")
    assert o == JobOptions(pages="1-3", auto_glossary=False, source="fr", target="ja", output_mode="target-only",
                           refresh_glossary=True)
    assert kw["ocr_backend"] is not None


def test_a_finish_with_the_translated_pages_job(job_run):
    ((_, _, o, _),) = job_run(only_cached=True, target="en")
    assert o.only_cached and o.target == "en" and not o.refresh_glossary
