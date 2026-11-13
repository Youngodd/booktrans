"""Interface every LLM provider implements, and the retried call everything above it uses."""
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
    for delay in (*RETRY_DELAYS, None):
        try:
            return backend.complete(system, text, max_tokens=max_tokens)
        except AuthError:
            raise
        except BackendError:
            if delay is None:
                raise
            time.sleep(delay)
