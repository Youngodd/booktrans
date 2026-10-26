import types

import openai
import pytest
import httpx

from booktrans.backends import BACKENDS, make_backend
from booktrans.backends.base import AuthError, BackendError
from booktrans.backends.openai_compat import PROVIDERS
from booktrans.usage import Usage


class FakeCompletions:
    def __init__(self, outcome):
        self.outcome, self.calls = outcome, []

    def create(self, **kw):
        self.calls.append(kw)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        msg = types.SimpleNamespace(content=" 你好 ")
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=msg)],
            usage=types.SimpleNamespace(prompt_tokens=11, completion_tokens=5))


def backend(outcome="ok", provider="qwen", **kw):
    b = make_backend(provider, usage=Usage(), api_key="k-123", **kw)
    b.client.chat = types.SimpleNamespace(completions=FakeCompletions(outcome))
    return b


def http_error(cls, status):
    req = httpx.Request("POST", "http://x")
    return cls("boom", response=httpx.Response(status, request=req), body=None)


def test_every_provider_is_registered():
    assert set(PROVIDERS) <= set(BACKENDS)


def test_complete_sends_system_and_user_and_records_usage():
    b = backend()
    assert b.complete("SYS", "hello") == "你好"
    call = b.client.chat.completions.calls[0]
    assert call["model"] == "qwen-plus"
    assert call["messages"] == [{"role": "system", "content": "SYS"},
                                {"role": "user", "content": "hello"}]
    assert b.usage.tokens["input_tokens"] == 11 and b.usage.tokens["output_tokens"] == 5


def test_ocr_uses_the_vision_model_and_an_image():
    b = backend()
    b.ocr_image(b"\xff\xd8jpeg", "read it")
    call = b.client.chat.completions.calls[0]
    assert call["model"] == "qwen-vl-max"
    parts = call["messages"][0]["content"]
    assert parts[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert b.supports_vision


def test_vision_model_can_be_chosen_and_deepseek_has_none():
    assert backend(vision_model="qwen-vl-plus").vision_model == "qwen-vl-plus"
    assert not backend(provider="deepseek").supports_vision


def test_rejected_key_is_an_auth_error_other_failures_are_backend_errors():
    with pytest.raises(AuthError):
        backend(http_error(openai.AuthenticationError, 401)).complete("s", "u")
    with pytest.raises(BackendError) as e:
        backend(http_error(openai.InternalServerError, 500)).complete("s", "u")
    assert not isinstance(e.value, AuthError)


def test_key_comes_from_the_environment_and_is_required(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    with pytest.raises(ValueError, match="DASHSCOPE_API_KEY"):
        make_backend("qwen")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "abc")
    assert make_backend("qwen").client.api_key == "abc"


def test_custom_provider_needs_base_url_and_model(monkeypatch):
    monkeypatch.delenv("BOOKTRANS_BASE_URL", raising=False)
    with pytest.raises(ValueError, match="BOOKTRANS_BASE_URL"):
        make_backend("openai-compatible", model="m", api_key="k")
    monkeypatch.setenv("BOOKTRANS_BASE_URL", "http://localhost:1/v1")
    with pytest.raises(ValueError, match="--model"):
        make_backend("openai-compatible", api_key="k")
    b = make_backend("openai-compatible", model="m", api_key="k")
    assert str(b.client.base_url).startswith("http://localhost:1/v1")


def test_a_refused_vision_call_names_the_model_and_the_providers_reason():
    err = http_error(openai.PermissionDeniedError, 403)
    err.message = "Model access denied."
    with pytest.raises(AuthError) as e:
        backend(err).ocr_image(b"jpeg", "read")
    text = str(e.value)
    assert "qwen-vl-max" in text and "Model access denied." in text and "k-123" not in text
