"""Interface every LLM provider implements, and the retried call everything above it uses."""
import sys
import time

RETRY_DELAYS = (5, 20, 60)  # seconds to wait before each retry of a failed call


class BackendError(RuntimeError):
    """A model call failed (network, quota...). Calls may be retried."""


class AuthError(BackendError):
    """The API key was rejected. Retrying cannot help."""


class LLMBackend:
    """A text-in/text-out model. Vision (for OCR) is optional."""

    supports_vision = False

    def __init__(self, model=None, usage=None):
        from ..usage import Usage
        self.model = model
        self.usage = usage or Usage()

    def complete(self, system, user, max_tokens=4096):
        """Return the model's text reply to `user` under the `system` prompt."""
        raise NotImplementedError

    def ocr_image(self, jpeg, prompt):
        """Return the text the model reads from a JPEG (bytes). Vision backends only."""
        raise NotImplementedError(f"{type(self).__name__} has no vision support")


def complete(backend, system, text, max_tokens):
    """backend.complete, retried when the call fails (dropped connection, rate limit).

    An AuthError is never retried (a wrong key stays wrong), and neither is anything that is not
    a BackendError, such as the spend limit stopping a call.
    """
    from .. import failure
    attempts = len(RETRY_DELAYS) + 1
    for n, delay in enumerate((*RETRY_DELAYS, None), 1):
        try:
            return backend.complete(system, text, max_tokens=max_tokens)
        except AuthError as e:
            raise AuthError(_said(failure.where(), who(backend), "was refused", e)) from e
        except BackendError as e:
            why = failure.SHORT_CAUSE[failure.classify(e)]
            if delay is None:
                raise BackendError(_said(failure.where(), who(backend), f"failed after {attempts} attempts ({why})", e)) from e
            task = failure.where()
            print(f"{'While ' + task + ': a' if task else 'A'}ttempt {n}/{attempts} failed ({why}); retrying in {delay}s",
                  file=sys.stderr, flush=True)
            time.sleep(delay)


def who(backend):
    """The backend and model, for messages: "qwen (qwen3.7-plus)"."""
    name = getattr(backend, "provider", None) or type(backend).__name__
    model = getattr(backend, "model", None)
    return f"{name} ({model})" if model else str(name)


def _said(task, backend_name, what, cause):
    return f"{task[:1].upper() + task[1:] + ': ' if task else ''}{backend_name} {what}: {cause}"
