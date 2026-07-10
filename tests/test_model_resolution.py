from __future__ import annotations

import json

import pytest

from whatsapp_chat_system.ai.provider import AIProviderError, AIResult
from whatsapp_chat_system.ai.service import AIService
from whatsapp_chat_system.config import AppConfig
from whatsapp_chat_system.rewriter import Rewriter
from whatsapp_chat_system.settings import AISettings

from conftest import create_profile


class RecordingProvider:
    def __init__(self) -> None:
        self.models: list[str] = []

    def chat(self, *, model, messages, response_format=None, temperature=None):
        self.models.append(model)
        return AIResult(
            content='{"message":"ok"}',
            model=model,
            request_id='req_1',
            usage={},
            latency_ms=1,
        )


def test_model_resolution_contact_over_account_over_global():
    service = AIService(RecordingProvider(), AISettings(default_model='global-model'))

    assert service.resolve_model(contact_model='contact-model', account_model='account-model').model == 'contact-model'
    assert service.resolve_model(contact_model='contact-model', account_model='account-model').source == 'contact_override'
    assert service.resolve_model(account_model='account-model').model == 'account-model'
    assert service.resolve_model(account_model='account-model').source == 'account_profile'
    assert service.resolve_model().model == 'global-model'
    assert service.resolve_model().source == 'global_default'


def test_service_passes_effective_model_to_provider():
    provider = RecordingProvider()
    service = AIService(provider, AISettings(default_model='global-model'))

    result = service.chat(
        messages=[{'role': 'user', 'content': 'hello'}],
        contact_model='contact-model',
        account_model='account-model',
    )

    assert provider.models == ['contact-model']
    assert result.model_resolution.model == 'contact-model'
    assert result.model_resolution.source == 'contact_override'
    assert result.result.request_id == 'req_1'


def test_real_app_config_and_rewriter_inherit_env_global_then_account_then_contact(monkeypatch, tmp_path):
    monkeypatch.setenv('WENDING_AI_DEFAULT_MODEL', 'env-global-model')
    profile = create_profile(tmp_path / 'model-inheritance')
    config = AppConfig.from_profile(profile)
    provider = RecordingProvider()
    service = AIService(provider, config.ai_settings)
    rewriter = Rewriter(config, lambda *args, **kwargs: None, ai_service=service)

    assert config.web_settings['reply']['ai_model'] == ''
    rewriter.rewrite({'id': 'u', 'name': 'U'}, '你好', 'Preferred language: Thai')
    assert provider.models == ['env-global-model']

    config.web_settings['reply']['ai_model'] = 'account-model'
    rewriter.rewrite({'id': 'u', 'name': 'U'}, '你好', 'Preferred language: Thai')
    rewriter.rewrite(
        {'id': 'u', 'name': 'U'},
        '你好',
        'Preferred language: Thai',
        reply_overrides={'ai_model': 'contact-model'},
    )
    assert provider.models == ['env-global-model', 'account-model', 'contact-model']


def test_existing_explicit_account_model_is_preserved(monkeypatch, tmp_path):
    monkeypatch.setenv('WENDING_AI_DEFAULT_MODEL', 'env-global-model')
    profile = create_profile(tmp_path / 'existing-account-model')
    settings_path = profile / 'web-settings.json'
    stored = json.loads(settings_path.read_text())
    stored['reply']['ai_model'] = 'explicit-account-model'
    settings_path.write_text(json.dumps(stored))

    config = AppConfig.from_profile(profile)

    assert config.web_settings['reply']['ai_model'] == 'explicit-account-model'


def test_ai_service_audits_success_without_messages_or_secrets():
    events = []
    provider = RecordingProvider()
    settings = AISettings(api_key='unit-test-secret', default_model='global-model')
    service = AIService(provider, settings, audit_logger=lambda event, **fields: events.append((event, fields)))

    service.chat(messages=[{'role': 'user', 'content': 'complete private message'}])

    assert len(events) == 1
    event, fields = events[0]
    assert event == 'ai_request_audit'
    assert fields == {
        'provider': 'wendingai',
        'request_id': 'req_1',
        'effective_model': 'global-model',
        'model_source': 'global_default',
        'latency_ms': 1,
        'status': 'success',
        'usage': {},
        'error_code': None,
        'retryable': None,
    }
    serialized = json.dumps(events)
    assert 'unit-test-secret' not in serialized
    assert 'complete private message' not in serialized


class FailingProvider:
    def chat(self, *, model, messages, response_format=None, temperature=None):
        raise AIProviderError(
            code='rate_limited',
            message='rate limited',
            retryable=True,
            status_code=429,
            request_id='req_failed',
        )


def test_ai_service_audits_provider_failure_and_reraises():
    events = []
    service = AIService(
        FailingProvider(),
        AISettings(api_key='unit-test-secret', default_model='global-model'),
        audit_logger=lambda event, **fields: events.append((event, fields)),
    )

    with pytest.raises(AIProviderError):
        service.chat(
            messages=[{'role': 'user', 'content': 'complete private message'}],
            account_model='account-model',
        )

    event, fields = events[0]
    assert event == 'ai_request_audit'
    assert fields['provider'] == 'wendingai'
    assert fields['request_id'] == 'req_failed'
    assert fields['effective_model'] == 'account-model'
    assert fields['model_source'] == 'account_profile'
    assert fields['latency_ms'] >= 0
    assert fields['status'] == 'failed'
    assert fields['usage'] == {}
    assert fields['error_code'] == 'rate_limited'
    assert fields['retryable'] is True
    serialized = json.dumps(events)
    assert 'unit-test-secret' not in serialized
    assert 'complete private message' not in serialized
