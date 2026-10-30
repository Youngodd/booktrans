"""Backend registry. To add a provider that speaks the OpenAI protocol, add an entry
to PROVIDERS in openai_compat.py. For any other kind, write a LLMBackend subclass in a
new file and add it to BACKENDS (imported lazily so unused SDKs aren't required)."""
from .base import LLMBackend
from .openai_compat import PROVIDERS

__all__ = ["BACKENDS", "LLMBackend", "PROVIDERS", "catalog", "make_backend"]


def _claude_cli():
    from .claude_cli import ClaudeCLIBackend
    return ClaudeCLIBackend


def _api():
    from .anthropic_api import AnthropicBackend
    return AnthropicBackend


def _openai_compat(provider):
    def load():
        from functools import partial
        from .openai_compat import OpenAICompatBackend
        return partial(OpenAICompatBackend, provider=provider)
    return load


BACKENDS = {"claude-cli": _claude_cli, "api": _api,
            **{name: _openai_compat(name) for name in PROVIDERS}}


def make_backend(name, model=None, usage=None, api_key=None, vision_model=None):
    """Build the backend `name`. `api_key` overrides the provider's environment variable."""
    extra = {k: v for k, v in (("api_key", api_key), ("vision_model", vision_model))
             if v is not None}
    if name in ("claude-cli", "api"):  # these use `model` for reading images too
        extra.pop("vision_model", None)
    if name == "claude-cli":
        extra.pop("api_key", None)
    return BACKENDS[name]()(model=model, usage=usage, **extra)


def catalog():
    """What the desktop pickers offer for each provider: the default and the short list of
    models (default first) for text and for reading scanned pages. `ocr_shared` is true when
    the one chosen model also reads images (Anthropic); an empty `vision_models` means no OCR."""
    from .anthropic_api import DEFAULT_MODEL, MODELS
    out = {"api": {"model": DEFAULT_MODEL, "models": MODELS, "vision": DEFAULT_MODEL,
                   "vision_models": [], "ocr_shared": True}}
    for name, cfg in PROVIDERS.items():
        out[name] = {"model": cfg["model"], "models": cfg["models"], "vision": cfg["vision"],
                     "vision_models": cfg["vision_models"], "ocr_shared": False}
    return out
