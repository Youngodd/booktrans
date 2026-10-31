"""A spend limit per book: count what the model calls cost and stop before going over.

The meter wraps a backend, so every paid call is counted: translation, the retries of a failed
call, glossary, OCR. Before each call it checks that the call would still fit under the limit;
when it would not, it raises SpendLimitReached and nothing more is paid for. The pages already
translated are in the cache, so a later run (with a higher limit) resumes without paying again.
What was spent is kept in a file next to the output, so the limit is per book across runs.

PRICES are ESTIMATES, not measured figures: only the Anthropic cost per page (about US$0.017)
was measured on a scanned book, and DeepSeek's (about ¥0.001) in one run. The rates below are list prices recalled by the maintainer and
have not been checked against each provider's current price page; check them before relying on
the guard for real money. Conversions use USD_CNY.
"""
import json
import math
from pathlib import Path

from .backends.base import LLMBackend
from .fsutil import write_json

DEFAULT_LIMIT_CNY = 10.0  # yuan per book unless the user chooses another limit (0 = no limit)
USD_CNY = 7.2             # estimate

# (input, output) yuan per million tokens. "text" is the translating model, "vision" the OCR model.
PRICES = {
    "api": {"text": (3 * USD_CNY, 15 * USD_CNY), "vision": (3 * USD_CNY, 15 * USD_CNY)},  # Sonnet-class list price, UNVERIFIED for the current model
    "qwen": {"text": (0.8, 2.0), "vision": (3.0, 9.0)},                                    # UNVERIFIED
    "qwen-intl": {"text": (0.4 * USD_CNY, 1.2 * USD_CNY), "vision": (0.8 * USD_CNY, 3.2 * USD_CNY)},  # UNVERIFIED
    # deepseek-flash, peak-hour cache-miss list price $0.30 in / $1.20 out per 1M tokens, read from
    # api-docs.deepseek.com on 2026-10-31 and converted at USD_CNY (off-peak is half; cache hits far less)
    "deepseek": {"text": (0.3 * USD_CNY, 1.2 * USD_CNY), "vision": (0.3 * USD_CNY, 1.2 * USD_CNY)},
}
CACHE_WRITE_FACTOR, CACHE_READ_FACTOR = 1.25, 0.1  # Anthropic prompt caching, relative to the input rate

# Used only for the estimate shown before a book starts and for "how much is left":
# a page of ordinary text is roughly this many tokens in and out, prompts included.
EST_TOKENS_PER_PAGE = (1500, 1500)
MEASURED_ANTHROPIC_USD_PER_PAGE = 0.017  # measured on a scanned history book
MEASURED_CNY_PER_PAGE = {"deepseek": 0.001}  # one run: 110 pages cost about ¥0.1 (2026-10-30); far below the token guess


class SpendLimitReached(Exception):
    """The next call would take the book's spend over its limit. Not a BackendError: retries
    and the glossary's "carry on without it" must not swallow it."""

    def __init__(self, spent, limit):
        super().__init__(f"Spend limit reached: ¥{spent:.2f} of ¥{limit:.2f}.")
        self.spent, self.limit = spent, limit


def est_cny_per_page():
    """Rough cost of one page for each provider, in yuan. Anthropic uses the measured figure."""
    out = {"api": MEASURED_ANTHROPIC_USD_PER_PAGE * USD_CNY, **MEASURED_CNY_PER_PAGE}
    for name, rates in PRICES.items():
        if name not in out:
            tin, tout = EST_TOKENS_PER_PAGE
            out[name] = (tin * rates["text"][0] + tout * rates["text"][1]) / 1e6
    return {k: round(v, 3) for k, v in out.items()}


def _tokens(usage):
    return dict(usage.tokens), usage.cost_usd


class Meter:
    """Spent-so-far and the limit for one book. `limit` of 0 or None counts but never stops.

    `path` (a .json file) keeps the total across runs; pass `prices` to override PRICES (tests).
    """

    def __init__(self, limit=DEFAULT_LIMIT_CNY, path=None, prices=None):
        self.limit = float(limit or 0)
        self.path = Path(path) if path else None
        self.prices = prices or PRICES
        self.spent = 0.0
        if self.path and self.path.exists():
            try:
                self.spent = float(json.loads(self.path.read_text(encoding="utf-8"))["spent_cny"])
            except (OSError, ValueError, KeyError):
                pass

    def cost(self, provider, kind, tokens, cost_usd=0.0):
        """Yuan for one call's token counts (or the CLI backend's reported dollars)."""
        if cost_usd:
            return cost_usd * USD_CNY
        rate = self.prices.get(provider, {}).get(kind)
        if not rate:
            return 0.0
        tin = tokens.get("input_tokens", 0) + CACHE_WRITE_FACTOR * tokens.get("cache_creation_input_tokens", 0) \
            + CACHE_READ_FACTOR * tokens.get("cache_read_input_tokens", 0)
        return (tin * rate[0] + tokens.get("output_tokens", 0) * rate[1]) / 1e6

    def add(self, yuan):
        self.spent += yuan
        if self.path and yuan:
            write_json(self.path, {"spent_cny": round(self.spent, 6)})

    def check(self, provider, kind, in_chars, max_tokens):
        """Raise SpendLimitReached unless a call of about this size still fits under the limit."""
        if self.limit <= 0:
            return
        tin = max(in_chars / 3, 1)  # about 3 characters per token is on the cautious side
        tout = min(tin * 1.5, max_tokens)
        projected = self.spent + self.cost(provider, kind, {"input_tokens": tin, "output_tokens": tout})
        if self.spent >= self.limit or projected > self.limit:
            raise SpendLimitReached(self.spent, self.limit)


def price_approx(provider, model="", ocr_model="", ocr=False):
    """True when a chosen model is not the one the provider's rate was written for (the guard
    then prices it at the provider's rate, which may be too low or too high)."""
    from .backends import catalog
    cfg = catalog().get(provider)
    if not cfg:
        return False
    return bool((model and model != cfg["model"]) or (ocr and ocr_model and ocr_model != cfg["vision"]))


def provider_of(backend):
    return getattr(backend, "provider", None) or \
        ("api" if type(backend).__name__ == "AnthropicBackend" else "claude-cli"
         if type(backend).__name__ == "ClaudeCLIBackend" else "unknown")


class Metered(LLMBackend):
    """`backend` with every call counted by `meter` and stopped at the limit."""

    def __init__(self, backend, meter):
        super().__init__(backend.model, backend.usage)
        self.inner, self.meter = backend, meter
        self.supports_vision = backend.supports_vision
        self.provider = provider_of(backend)

    def _counted(self, kind, call, in_chars, max_tokens):
        self.meter.check(self.provider, kind, in_chars, max_tokens)
        before, before_usd = _tokens(self.inner.usage)
        try:
            return call()
        finally:  # a call that fails after the provider billed it still costs money
            after, after_usd = _tokens(self.inner.usage)
            delta = {k: after[k] - before[k] for k in after}
            self.meter.add(self.meter.cost(self.provider, kind, delta, after_usd - before_usd))

    def complete(self, system, user, max_tokens=4096):
        return self._counted("text", lambda: self.inner.complete(system, user, max_tokens),
                             len(system) + len(user), max_tokens)

    def ocr_image(self, jpeg, prompt):
        # a page image costs about this many input tokens: counted as characters for the check
        return self._counted("vision", lambda: self.inner.ocr_image(jpeg, prompt), 4500, 4096)


class NoCalls(LLMBackend):
    """For a run that must not pay for anything (finishing with the pages already translated)."""

    def complete(self, system, user, max_tokens=4096):
        raise RuntimeError("A call was attempted in a run that must not spend anything.")

    ocr_image = complete


def rest_estimate(spent, done, total):
    """Rough yuan still needed, from the average per page so far; None when it cannot be told."""
    if not (done and total and done < total) or not spent:
        return None
    return round(spent / done * (total - done), 2) if math.isfinite(spent) else None
