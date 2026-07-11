from __future__ import annotations

import tempfile

from whatsapp_chat_system.ai.provider import AIProviderError, AIResult
from whatsapp_chat_system.ai.service import AIService
from whatsapp_chat_system.rewriter import Rewriter
from whatsapp_chat_system.settings import AISettings


class DummyConfig:
    ai_settings = AISettings(default_model="global-model")
    web_settings = {
        "reply": {
            "ai_model": "account-model",
            "custom_system_prompt": "",
            "default_reply_style": "",
        }
    }

    class _Paths:
        memory_dir = tempfile.mkdtemp()

    paths = _Paths()


class RecordingProvider:
    def __init__(self, contents: list[str]) -> None:
        self.contents = list(contents)
        self.calls: list[dict] = []

    def chat(self, *, model, messages, response_format=None, temperature=None):
        self.calls.append(
            {
                "model": model,
                "messages": messages,
                "response_format": response_format,
                "temperature": temperature,
            }
        )
        return AIResult(
            content=self.contents.pop(0),
            model=model,
            request_id="req_rewriter",
            usage={},
            latency_ms=1,
        )


def test_rewriter_smart_translate_and_auto_translate_use_ai_service():
    provider = RecordingProvider(
        [
            '{"language":"Thai","message":"สวัสดี"}',
            '{"message":"สวัสดี"}',
            '{"zh":"你好"}',
        ]
    )
    service = AIService(provider, AISettings(default_model="global-model"))
    rewriter = Rewriter(DummyConfig(), lambda *args, **kwargs: None, ai_service=service)

    smart = rewriter.rewrite(
        {"id": "u", "name": "User"},
        "你好",
        "Preferred language: Thai",
        reply_overrides={"ai_model": "contact-model"},
    )
    translated = rewriter.translate_only(
        {"id": "u", "name": "User"}, "你好", "Preferred language: Thai"
    )
    auto = rewriter.translate_to_zh("ສະບາຍດີ", "Lao")

    assert smart.message == "สวัสดี"
    assert translated.message == "สวัสดี"
    assert auto == "你好"
    assert [call["model"] for call in provider.calls] == [
        "contact-model",
        "account-model",
        "account-model",
    ]


def test_rewriter_default_ai_service_injects_existing_logger_for_audit():
    events = []
    rewriter = Rewriter(
        DummyConfig(), lambda event, **fields: events.append((event, fields))
    )

    assert rewriter.ai_service.audit_logger is rewriter.logger


class ProviderFailure:
    def chat(self, *, model, messages, response_format=None, temperature=None):
        raise AIProviderError(
            code="upstream_error",
            message="upstream unavailable",
            retryable=True,
            status_code=503,
            request_id="req_upstream",
        )


def test_rewriter_provider_failure_preserves_fallback_and_error_metadata():
    service = AIService(ProviderFailure(), AISettings(default_model="global-model"))
    rewriter = Rewriter(DummyConfig(), lambda *args, **kwargs: None, ai_service=service)

    result = rewriter.rewrite(
        {"id": "u", "name": "User"}, "你好", "Preferred language: Thai"
    )
    translated = rewriter.translate_only(
        {"id": "u", "name": "User"}, "你好", "Preferred language: Thai"
    )

    assert result.used_fallback is True
    assert result.message == "你好"
    assert result.error == {
        "code": "upstream_error",
        "retryable": True,
        "request_id": "req_upstream",
    }
    assert translated.used_fallback is True
    assert translated.error == result.error


def test_rewriter_non_provider_validation_fallback_has_no_ai_error():
    provider = RecordingProvider(["not-json"])
    service = AIService(provider, AISettings(default_model="global-model"))
    rewriter = Rewriter(DummyConfig(), lambda *args, **kwargs: None, ai_service=service)

    result = rewriter.rewrite(
        {"id": "u", "name": "User"}, "你好", "Preferred language: Thai"
    )

    assert result.used_fallback is True
    assert result.error is None
