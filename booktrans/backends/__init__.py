"""Backend registry. To add a provider: write a LLMBackend subclass in a new
file and add it to BACKENDS (imported lazily so unused SDKs aren't required)."""
from .base import LLMBackend

__all__ = ["BACKENDS", "LLMBackend", "make_backend"]


def _claude_cli():
    from .claude_cli import ClaudeCLIBackend
    return ClaudeCLIBackend


def _api():
    from .anthropic_api import AnthropicBackend
    return AnthropicBackend


BACKENDS = {"claude-cli": _claude_cli, "api": _api}


def make_backend(name, model=None, usage=None):
    return BACKENDS[name]()(model=model, usage=usage)
