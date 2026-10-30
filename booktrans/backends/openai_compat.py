"""Backends for any provider that speaks the OpenAI chat protocol (Qwen, DeepSeek, ...).

To add a supplier, add one entry to PROVIDERS. Nothing else changes.
"""
import base64
import os

from .base import AuthError, BackendError, LLMBackend

# base_url   the provider's OpenAI-compatible endpoint
# key_env    environment variable holding the API key (used when none is passed in)
# model      default text model;  vision: default model for reading scanned pages (or None)
# models / vision_models   the short lists the desktop pickers offer, default first (one line to add a model)
PROVIDERS = {
    "qwen": {  # Alibaba Cloud Model Studio, mainland China account
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "key_env": "DASHSCOPE_API_KEY", "model": "qwen-plus", "vision": "qwen-vl-max",
        "models": ["qwen-plus", "qwen-max", "qwen-turbo"], "vision_models": ["qwen-vl-max", "qwen-vl-plus"],
        "label": "Qwen (Alibaba Cloud, China)"},
    "qwen-intl": {  # the same service for international accounts (Singapore)
        "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "key_env": "DASHSCOPE_API_KEY", "model": "qwen-plus", "vision": "qwen-vl-max",
        "models": ["qwen-plus", "qwen-max", "qwen-turbo"], "vision_models": ["qwen-vl-max", "qwen-vl-plus"],
        "label": "Qwen (Alibaba Cloud, international)"},
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "key_env": "DEEPSEEK_API_KEY", "model": "deepseek-chat", "vision": None,
        "models": ["deepseek-chat", "deepseek-reasoner"], "vision_models": [],
        "label": "DeepSeek"},
    "openai-compatible": {  # anything else: set BOOKTRANS_BASE_URL, BOOKTRANS_API_KEY and --model
        "base_url": None, "key_env": "BOOKTRANS_API_KEY", "model": None, "vision": None,
        "models": [], "vision_models": [],
        "label": "Other (BOOKTRANS_BASE_URL)"},
}
TIMEOUT = 180


class OpenAICompatBackend(LLMBackend):
    def __init__(self, model=None, usage=None, api_key=None, vision_model=None,
                 provider="qwen"):
        import openai
        cfg = PROVIDERS[provider]
        super().__init__(model or cfg["model"], usage)
        self.provider = provider  # the spend guard prices calls by provider
        base_url = cfg["base_url"] or os.environ.get("BOOKTRANS_BASE_URL")
        if not base_url:
            raise ValueError(f"Set BOOKTRANS_BASE_URL to use the {provider} backend.")
        if not self.model:
            raise ValueError(f"The {provider} backend needs --model.")
        self.vision_model = vision_model or cfg["vision"]
        self.supports_vision = bool(self.vision_model)
        key = api_key or os.environ.get(cfg["key_env"])
        if not key:
            raise ValueError(f"No API key: set {cfg['key_env']}.")
        self.client = openai.OpenAI(api_key=key, base_url=base_url, timeout=TIMEOUT,
                                    max_retries=0)  # retries are done by translate.py

    def _send(self, model, messages, max_tokens):
        import openai
        try:
            resp = self.client.chat.completions.create(
                model=model, messages=messages, max_tokens=max_tokens)
        except (openai.AuthenticationError, openai.PermissionDeniedError) as e:
            why = (getattr(e, "message", "") or "")[:300]  # the provider's own reason (never contains the key)
            raise AuthError(f"The provider refused the call to model \"{model}\" ({why or 'no reason given'}). "
                            "Check that the key is correct, the account has credit, and this model is "
                            "activated for it (scanned pages use the vision model).") from e
        except openai.OpenAIError as e:
            raise BackendError(f"API error: {e}") from e
        u = resp.usage
        self.usage.record({"input_tokens": getattr(u, "prompt_tokens", 0),
                           "output_tokens": getattr(u, "completion_tokens", 0)})
        if not resp.choices:
            raise BackendError("The model returned no answer.")
        return (resp.choices[0].message.content or "").strip()

    def complete(self, system, user, max_tokens=4096):
        return self._send(self.model, [{"role": "system", "content": system},
                                       {"role": "user", "content": user}], max_tokens)

    def ocr_image(self, jpeg, prompt):
        if not self.supports_vision:
            raise NotImplementedError("This provider has no vision model; pass --ocr-model.")
        url = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()
        return self._send(self.vision_model, [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": url}},
            {"type": "text", "text": prompt}]}], 4096)
