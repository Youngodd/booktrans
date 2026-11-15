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
# Qwen ids carry a version number. Read from the Model Studio model lists (help.aliyun.com/zh/model-studio/
# text-generation-model and its alibabacloud.com/help/en twin, the same on both) on 2026-11-15: the recommended
# models are qwen3.7-plus (balanced), qwen3.8-max and qwen3.8-flash; the unnumbered qwen-plus / qwen-max are
# listed as older models and the qwen-vl-* ids are gone: Plus and Max read images themselves.
QWEN_MODELS = ["qwen3.7-plus", "qwen3.8-max", "qwen3.8-flash"]
QWEN_VISION = ["qwen3.7-plus", "qwen3.8-max"]
# These models think by default, paid as output and not needed for translation (see DeepSeek below).
QWEN_EXTRA = {"enable_thinking": False}
PROVIDERS = {
    "qwen": {  # Alibaba Cloud Model Studio, mainland China account
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "key_env": "DASHSCOPE_API_KEY", "model": "qwen3.7-plus", "vision": "qwen3.7-plus",
        "models": QWEN_MODELS, "vision_models": QWEN_VISION, "extra_body": QWEN_EXTRA,
        "label": "Qwen (Alibaba Cloud, China)"},
    "qwen-intl": {  # the same service for international accounts (Singapore)
        "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "key_env": "DASHSCOPE_API_KEY", "model": "qwen3.7-plus", "vision": "qwen3.7-plus",
        "models": QWEN_MODELS, "vision_models": QWEN_VISION, "extra_body": QWEN_EXTRA,
        "label": "Qwen (Alibaba Cloud, international)"},
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "key_env": "DEEPSEEK_API_KEY", "model": "deepseek-flash", "vision": None,  # deepseek-chat/-reasoner were retired 2026-07-24
        "models": ["deepseek-flash", "deepseek-v4-pro"], "vision_models": [],
        # DeepSeek thinks by default and the thinking is paid out of max_tokens: a page's whole
        # allowance went on it and the answer came back empty. Translation does not need it.
        "extra_body": {"thinking": {"type": "disabled"}},
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
        self.extra_body = cfg.get("extra_body")  # provider-specific request fields
        self.client = openai.OpenAI(api_key=key, base_url=base_url, timeout=TIMEOUT,
                                    max_retries=0)  # retries are done by translate.py

    def _send(self, model, messages, max_tokens):
        import openai
        try:
            resp = self.client.chat.completions.create(
                model=model, messages=messages, max_tokens=max_tokens, extra_body=self.extra_body)
        except (openai.AuthenticationError, openai.PermissionDeniedError) as e:
            why = (getattr(e, "message", "") or "")[:300]  # the provider's own reason (never contains the key)
            raise AuthError(f"The provider refused the call to model \"{model}\" ({why or 'no reason given'}). "
                            "Check that the key is correct, the account has credit, and this model is "
                            "activated for it (scanned pages use the vision model).") from e
        except openai.OpenAIError as e:
            raise BackendError(f"API error from {self.provider} (model {model}): {e}") from e
        u = resp.usage
        self.usage.record({"input_tokens": getattr(u, "prompt_tokens", 0),
                           "output_tokens": getattr(u, "completion_tokens", 0)})
        if not resp.choices:
            raise BackendError("The model returned no answer.")
        text = (resp.choices[0].message.content or "").strip()
        if not text and getattr(resp.choices[0], "finish_reason", None) == "length":
            raise BackendError(f"The model \"{model}\" used its whole answer allowance ({max_tokens} tokens) "
                               "without writing an answer (a thinking model spends it on reasoning).")
        return text

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
