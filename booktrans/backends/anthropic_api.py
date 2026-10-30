"""Backend for the Anthropic API (needs ANTHROPIC_API_KEY)."""
import base64

from .base import AuthError, BackendError, LLMBackend

DEFAULT_MODEL = "claude-sonnet-5-5"
MODELS = [DEFAULT_MODEL, "claude-opus-5-5", "claude-haiku-5-5"]  # the desktop picker; the one model also reads scanned pages


class AnthropicBackend(LLMBackend):
    supports_vision = True

    def __init__(self, model=None, usage=None, api_key=None):
        import anthropic
        super().__init__(model or DEFAULT_MODEL, usage)
        self.client = anthropic.Anthropic(api_key=api_key)  # None: use ANTHROPIC_API_KEY

    def _send(self, messages, max_tokens, **kw):
        import anthropic
        try:
            msg = self.client.messages.create(model=self.model, max_tokens=max_tokens,
                                              messages=messages, **kw)
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
            raise AuthError("The API key was rejected. Check that it is correct, "
                            "has credit and may use this model.") from e
        except anthropic.APIError as e:
            raise BackendError(f"Anthropic API error: {e}") from e
        self.usage.record(msg.usage)
        return "".join(b.text for b in msg.content if b.type == "text").strip()

    def complete(self, system, user, max_tokens=4096):
        return self._send([{"role": "user", "content": user}], max_tokens, system=system)

    def ocr_image(self, jpeg, prompt):
        return self._send([{"role": "user", "content": [
            {"type": "image", "source": {
                "type": "base64", "media_type": "image/jpeg",
                "data": base64.b64encode(jpeg).decode()}},
            {"type": "text", "text": prompt},
        ]}], 4096)
