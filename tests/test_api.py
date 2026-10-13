import pytest
from pypdf import PdfReader
import booktrans.translate as tr
from booktrans.backends.base import BackendError
from booktrans.layout import collect_layout
from booktrans.pipeline import count_pages, default_output, translate_book
from tests.conftest import FakeBackend


def test_translate_book_reports_progress(text_pdf, tmp_path, fake):
    events = []
    out = translate_book(text_pdf, tmp_path / "o.pdf", fake,
                         progress=lambda *a: events.append(a))
    assert len(PdfReader(str(out)).pages) == 6
    stages = [e[0] for e in events]
    assert {"scan", "translate", "render"} <= set(stages)
    assert events[-1][1] == events[-1][2]  # the last event is "all done"
    assert [e[1] for e in events if e[0] == "translate"] == [1, 2, 3]


def test_translate_book_resumes_from_cache(text_pdf, tmp_path):
    out = tmp_path / "o.pdf"
    translate_book(text_pdf, out, FakeBackend())
    second = FakeBackend()
    translate_book(text_pdf, out, second)
    assert second.calls == []


def test_count_pages_and_default_output(text_pdf, tmp_path):
    assert count_pages(text_pdf) == 3
    assert count_pages(text_pdf, "2-3") == 2
    assert default_output(tmp_path / "a.pdf", "1 - 5").name == "a_bilingual pages 1-5.pdf"


def test_failed_call_is_retried_then_succeeds(monkeypatch, fake):
    monkeypatch.setattr(tr.time, "sleep", lambda s: None)
    failures = iter([True, True, False])

    def reply(user):
        if next(failures):
            raise BackendError("connection refused")
        return "译"
    fake.reply = reply
    assert tr.translate(fake, "Hello") == "译"
    assert len(fake.calls) == 3


def test_failed_call_gives_up_after_retries(monkeypatch, fake):
    monkeypatch.setattr(tr.time, "sleep", lambda s: None)

    def reply(user):
        raise BackendError("down")
    fake.reply = reply
    with pytest.raises(BackendError):
        tr.translate(fake, "Hello")
    assert len(fake.calls) == len(tr.RETRY_DELAYS) + 1


def test_collect_layout_analyses_each_page_once(text_pdf, monkeypatch):
    import booktrans.layout as layout
    seen = []
    real = layout.page_blocks
    monkeypatch.setattr(layout, "page_blocks", lambda p: seen.append(p.number) or real(p))
    collect_layout(text_pdf, [0, 1, 2])
    assert sorted(seen) == [0, 1, 2]
