import argparse
import io
import json
import sys

import pytest
from pypdf import PdfReader

from booktrans import cli, spend, translate
from booktrans.pipeline import translate_book
from booktrans.spend import Meter, SpendLimitReached
from tests.conftest import PricedBackend


def run(book, out, backend, limit, **kw):
    meter = Meter(limit, out.with_suffix(".spend.json"))
    try:
        translate_book(book, out, backend, auto_glossary=False, meter=meter, **kw)
    finally:
        run.meter = meter
    return meter


def cached_pages(out):
    return sorted(json.loads(out.with_suffix(".cache.json").read_text(encoding="utf-8")))


def test_a_book_under_the_limit_finishes_and_the_spend_is_kept(text_pdf, tmp_path):
    out, b = tmp_path / "o.pdf", PricedBackend()
    meter = run(text_pdf, out, b, 100)
    assert out.exists() and meter.spent == 3.0 and len(b.calls) == 3
    assert json.loads(out.with_suffix(".spend.json").read_text())["spent_cny"] == 3.0


def test_over_the_limit_stops_saves_the_cache_and_reports_the_spend(text_pdf, tmp_path):
    out, b = tmp_path / "o.pdf", PricedBackend()
    with pytest.raises(SpendLimitReached) as e:
        run(text_pdf, out, b, 2.5)
    assert (e.value.spent, e.value.limit) == (2.0, 2.5)  # a third call would cost about 1 more: stop
    assert len(b.calls) == 2 and cached_pages(out) == ["L0", "L1"]  # finished pages are kept
    assert not out.exists()


def test_resuming_with_a_higher_limit_does_not_pay_again_for_cached_pages(text_pdf, tmp_path):
    out = tmp_path / "o.pdf"
    with pytest.raises(SpendLimitReached):
        run(text_pdf, out, PricedBackend(), 2.5)
    b2 = PricedBackend()
    meter = run(text_pdf, out, b2, 10)
    assert len(b2.calls) == 1  # only the page that was left
    assert meter.spent == 3.0  # the total is per book, across runs
    assert out.exists()


def test_a_limit_at_or_below_what_is_spent_stops_at_once(text_pdf, tmp_path):
    out = tmp_path / "o.pdf"
    run(text_pdf, out, PricedBackend(), 100)
    b = PricedBackend()
    with pytest.raises(SpendLimitReached):
        run(text_pdf, out, b, 3.0, redo="1")  # spent 3.0 already, limit 3.0
    assert b.calls == []


def test_retries_count_toward_the_spend(text_pdf, tmp_path, monkeypatch):
    monkeypatch.setattr(translate, "RETRY_DELAYS", (0, 0, 0))
    out, b = tmp_path / "o.pdf", PricedBackend(fail_first=1)
    meter = run(text_pdf, out, b, 100, pages="1")
    assert len(b.calls) == 1 and meter.spent == 2.0  # a billed failure plus the retry


def test_retries_cannot_run_past_the_limit(text_pdf, tmp_path, monkeypatch):
    monkeypatch.setattr(translate, "RETRY_DELAYS", (0, 0, 0))
    out = tmp_path / "o.pdf"
    with pytest.raises(SpendLimitReached):  # every attempt fails but is billed
        run(text_pdf, out, PricedBackend(fail_first=99), 2.5, pages="1")
    assert run.meter.spent <= 3.0


@pytest.mark.parametrize("limit", [0, None])
def test_no_limit_means_no_stop(text_pdf, tmp_path, limit):
    meter = run(text_pdf, tmp_path / "o.pdf", PricedBackend(), limit)
    assert meter.spent == 3.0  # still counted, never stopped


def test_finishing_with_the_translated_pages_spends_nothing(text_pdf, tmp_path):
    out = tmp_path / "o.pdf"
    with pytest.raises(SpendLimitReached):
        run(text_pdf, out, PricedBackend(), 2.5)
    b = PricedBackend()
    translate_book(text_pdf, out, b, only_cached=True)
    assert b.calls == [] and len(PdfReader(str(out)).pages) == 4  # 2 pages, each with its translation


def test_finishing_with_nothing_translated_is_an_error(text_pdf, tmp_path):
    with pytest.raises(ValueError, match="Nothing has been translated"):
        translate_book(text_pdf, tmp_path / "o.pdf", PricedBackend(), only_cached=True)


def test_the_glossary_names_already_paid_for_are_kept(tmp_path):
    book = tmp_path / "b.txt"
    book.write_text(("Alice Walker met Bob Stone. " * 4 + "\n\n") * 3, encoding="utf-8")
    from booktrans.pipeline import draft_glossary
    path = tmp_path / "g.json"
    with pytest.raises(SpendLimitReached):
        draft_glossary(book, PricedBackend(reply="[1] 爱丽丝"), path, meter=Meter(0.01))
    assert path.exists()  # saved on the way out, even when nothing could be added


def test_prices_and_estimates_are_complete():
    est = spend.est_cny_per_page()
    assert set(est) >= {"api", "qwen", "qwen-intl", "deepseek"} and all(v > 0 for v in est.values())
    assert est["api"] == round(0.017 * spend.USD_CNY, 3)  # the measured Anthropic figure
    assert spend.rest_estimate(2.0, 2, 3) == 1.0 and spend.rest_estimate(0, 0, 3) is None


def test_cost_counts_cache_tokens_at_their_own_rates():
    m = Meter(0, prices={"p": {"text": (1e6, 1e6)}})
    assert m.cost("p", "text", {"input_tokens": 1, "output_tokens": 1,
                                "cache_creation_input_tokens": 1, "cache_read_input_tokens": 10}) \
        == pytest.approx(1 + 1.25 + 1.0 + 1)


# ---- command line ----

@pytest.fixture
def cli_run(monkeypatch, text_pdf, tmp_path):
    out = tmp_path / "o.pdf"
    monkeypatch.setattr(cli, "make_backend", lambda *a, **k: PricedBackend())

    def go(*extra):
        monkeypatch.setattr(sys, "argv", ["booktrans", str(text_pdf), "-o", str(out), "--backend", "api",
                                          "--no-auto-glossary", *extra])
        cli.main()
    return go, out


def test_cli_non_interactive_stop_has_its_own_exit_code_and_can_be_finished(cli_run, capsys):
    go, out = cli_run
    with pytest.raises(SystemExit) as e:
        go("--max-spend", "2.5")
    assert e.value.code == cli.EXIT_SPEND_LIMIT
    assert "--max-spend" in capsys.readouterr().err and cached_pages(out) == ["L0", "L1"]
    go("--finish-partial")
    assert len(PdfReader(str(out)).pages) == 4


def test_cli_default_limit_is_ten_yuan_and_zero_means_none(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["booktrans", "b.pdf"])
    assert cli.parse_args().max_spend == 10.0
    monkeypatch.setattr(sys, "argv", ["booktrans", "b.pdf", "--max-spend", "0"])
    assert cli.parse_args().max_spend == 0


class Tty(io.StringIO):
    def isatty(self):
        return True


@pytest.mark.parametrize("answers,done", [(["r", "20"], True), (["f"], False), (["c"], False)])
def test_cli_interactive_choices(cli_run, monkeypatch, answers, done):
    go, out = cli_run
    monkeypatch.setattr(sys, "stdin", Tty())
    feed = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(feed))
    if answers == ["c"]:
        with pytest.raises(SystemExit, match="Cancelled"):
            go("--max-spend", "2.5")
        assert not out.exists() and cached_pages(out) == ["L0", "L1"]
    else:
        go("--max-spend", "2.5")
        assert out.exists()
        assert len(PdfReader(str(out)).pages) == (6 if done else 4)


def test_cli_rejects_a_new_limit_below_the_spend_and_asks_again(cli_run, monkeypatch):
    go, out = cli_run
    monkeypatch.setattr(sys, "stdin", Tty())
    feed = iter(["r", "1", "f"])  # 1 yuan is below the 2 already spent
    monkeypatch.setattr("builtins.input", lambda prompt="": next(feed))
    go("--max-spend", "2.5")
    assert len(PdfReader(str(out)).pages) == 4
