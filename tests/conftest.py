import re
import pytest
from booktrans.backends.base import LLMBackend


class FakeBackend(LLMBackend):
    """Text-only backend: numbered blocks come back as '[n] 译n', plain text as '译:<text>'."""
    def __init__(self, reply=None):
        super().__init__()
        self.calls = []
        self.reply = reply

    def complete(self, system, user, max_tokens=4096):
        self.calls.append(user)
        if self.reply is not None:
            return self.reply(user) if callable(self.reply) else self.reply
        nums = re.findall(r"(?m)^\[(\d+)\]", user)
        if nums:
            return "\n".join(f"[{n}] 译{n}" for n in nums)
        return "译:" + user


@pytest.fixture
def fake():
    return FakeBackend()


@pytest.fixture
def text_pdf(tmp_path):
    import fitz
    p = tmp_path / "book.pdf"
    doc = fitz.open()
    for n in range(3):
        pg = doc.new_page()
        pg.insert_text((72, 100), f"Chapter heading {n}", fontsize=20)
        pg.insert_textbox(fitz.Rect(72, 130, 500, 300),
                          "This is a body paragraph of the book that is long enough "
                          "to wrap across several lines on the page.", fontsize=11)
    doc.save(p)
    return p


class PricedBackend(FakeBackend):
    """A fake that records token usage; with the "fake" prices below every call costs ¥1."""
    provider = "fake"
    supports_vision = False

    def __init__(self, fail_first=0, reply=None):
        super().__init__(reply)
        self.fail_first = fail_first  # raise (after being "billed") on the first n calls

    def complete(self, system, user, max_tokens=4096):
        self.usage.record({"input_tokens": 1000, "output_tokens": 1000})  # ¥0.5 + ¥0.5
        if self.fail_first:
            self.fail_first -= 1
            from booktrans.backends.base import BackendError
            raise BackendError("dropped connection")
        return super().complete(system, user, max_tokens)


@pytest.fixture(autouse=True)
def fake_prices(monkeypatch):
    from booktrans import spend
    monkeypatch.setitem(spend.PRICES, "fake", {"text": (500.0, 500.0), "vision": (500.0, 500.0)})
