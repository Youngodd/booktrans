"""Interface every LLM provider implements."""


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
