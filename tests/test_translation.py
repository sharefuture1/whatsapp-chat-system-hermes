from fastapi.testclient import TestClient

from whatsapp_chat_system.web_api import build_app

from conftest import create_profile, seed_conversation


PASSWORD = 'test-pass'


def authed_client(profile):
    client = TestClient(build_app(str(profile)))
    token = client.post('/api/login', json={'password': PASSWORD}).json()['session_token']
    client.headers.update({'x-session-token': token})
    return client


def test_settings_default_has_auto_translate(tmp_path):
    profile = create_profile(tmp_path / 'p')
    client = authed_client(profile)
    body = client.get('/api/settings').json()
    assert body['web_settings']['message_ops']['auto_translate'] is True


def test_translate_endpoint_chinese_passthrough(tmp_path):
    profile = create_profile(tmp_path / 'p')
    client = authed_client(profile)
    resp = client.post('/api/messages/1/translate', json={
        'user_id': 'u@lid',
        'content': '你好',
    })
    body = resp.json()
    assert body['lang'] == 'Chinese'
    assert body['translated'] is None


def test_translate_endpoint_rejects_missing_fields(tmp_path):
    profile = create_profile(tmp_path / 'p')
    client = authed_client(profile)
    resp = client.post('/api/messages/1/translate', json={'content': 'hi'})
    assert resp.status_code == 400
    resp = client.post('/api/messages/1/translate', json={'user_id': 'u'})
    assert resp.status_code == 400


def test_auto_translate_off_short_circuits(tmp_path):
    profile = create_profile(tmp_path / 'p')
    seed_conversation(
        profile,
        user_id='u@lid',
        user_name='U',
        session_id='s',
        messages=[('user', 'ສະບາຍດີ', 1700000100.0)],
    )
    client = authed_client(profile)
    body = client.get('/api/settings').json()
    body['web_settings']['message_ops']['auto_translate'] = False
    client.put('/api/settings', json={'channels': body['channels'], 'web_settings': body['web_settings']})
    detail = client.get('/api/conversations/u@lid?page=1&page_size=10').json()
    assert detail['auto_translate'] is False
    assert detail['messages'][0]['translated'] is None


def test_legacy_delta_translation_cache_miss_does_not_call_provider(monkeypatch, tmp_path):
    from whatsapp_chat_system import web_api

    calls = []

    class ExplodingTranslationWorker:
        def translate_to_zh_result(self, text, source_lang):
            calls.append((text, source_lang))
            raise AssertionError('delta GET must not call the translation provider')

    monkeypatch.setattr(web_api, '_translation_worker', lambda config: ExplodingTranslationWorker())
    profile = create_profile(tmp_path / 'p-delta-cache-miss')
    seed_conversation(
        profile,
        user_id='delta-miss@lid',
        user_name='Delta Miss',
        session_id='s-delta-miss',
        messages=[('user', 'ສະບາຍດີ', 1700000100.0)],
    )
    client = authed_client(profile)

    response = client.get('/api/conversations/delta-miss@lid/messages?after_id=0&limit=10')

    assert response.status_code == 200
    assert calls == []
    assert response.json()['messages'][0]['translated'] is None


def test_legacy_delta_translation_returns_cached_value_without_provider(monkeypatch, tmp_path):
    from whatsapp_chat_system import web_api
    from whatsapp_chat_system.config import AppConfig
    from whatsapp_chat_system.translations import put_translation

    calls = []

    class ExplodingTranslationWorker:
        def translate_to_zh_result(self, text, source_lang):
            calls.append((text, source_lang))
            raise AssertionError('delta GET must only read the translation cache')

    monkeypatch.setattr(web_api, '_translation_worker', lambda config: ExplodingTranslationWorker())
    profile = create_profile(tmp_path / 'p-delta-cache-hit')
    seed_conversation(
        profile,
        user_id='delta-hit@lid',
        user_name='Delta Hit',
        session_id='s-delta-hit',
        messages=[('user', 'ສະບາຍດີ', 1700000100.0)],
    )
    client = authed_client(profile)
    config = AppConfig.from_profile(profile)
    message_id = 1
    put_translation(config.paths.memory_dir, 'delta-hit@lid', message_id, {
        'source_lang': 'Lao',
        'source_text': 'ສະບາຍດີ',
        'zh': '你好',
    })

    response = client.get('/api/conversations/delta-hit@lid/messages?after_id=0&limit=10')

    assert response.status_code == 200
    assert calls == []
    assert response.json()['messages'][0]['translated'] == '你好'


def test_translate_endpoint_accepts_v2_string_message_id(monkeypatch, tmp_path):
    from whatsapp_chat_system.rewriter import RewriteResult
    from whatsapp_chat_system import web_api

    class TranslationWorker:
        def translate_to_zh_result(self, text, source_lang):
            return RewriteResult(language='Chinese', message='你好', used_fallback=False, error=None)

    monkeypatch.setattr(web_api, '_translation_worker', lambda config: TranslationWorker())
    profile = create_profile(tmp_path / 'p-v2-translation')
    client = authed_client(profile)
    response = client.post('/api/messages/uuid-message-1/translate', json={
        'user_id': 'account:person@lid',
        'content': 'ສະບາຍດີ',
    })
    assert response.status_code == 200
    assert response.json()['message_id'] == 'uuid-message-1'
    assert response.json()['translated'] == '你好'


def test_translate_endpoint_provider_failure_is_structured(monkeypatch, tmp_path):
    from whatsapp_chat_system.rewriter import RewriteResult
    from whatsapp_chat_system import web_api

    class FailedTranslationWorker:
        def translate_to_zh_result(self, text, source_lang):
            return RewriteResult(
                language='Chinese',
                message=text,
                used_fallback=True,
                error={'code': 'upstream_error', 'retryable': True, 'request_id': 'req_translate'},
            )

    monkeypatch.setattr(web_api, '_translation_worker', lambda config: FailedTranslationWorker())
    profile = create_profile(tmp_path / 'p-translate-provider-failure')
    client = authed_client(profile)

    response = client.post('/api/messages/1/translate', json={
        'user_id': 'u@lid',
        'content': 'ສະບາຍດີ',
    })

    assert response.status_code == 200
    assert response.json() == {
        'success': False,
        'message_id': 1,
        'lang': 'Lao',
        'translated': None,
        'fallback_text': 'ສະບາຍດີ',
        'used_fallback': True,
        'error': {'code': 'upstream_error', 'retryable': True, 'request_id': 'req_translate'},
    }


def test_translate_endpoint_rejects_when_plugin_is_disabled(monkeypatch, tmp_path):
    from whatsapp_chat_system import web_api

    called = False

    class TranslationWorker:
        def translate_to_zh_result(self, text, source_lang):
            nonlocal called
            called = True
            raise AssertionError('provider must not run while plugin is disabled')

    monkeypatch.setattr(web_api, '_translation_worker', lambda config: TranslationWorker())
    profile = create_profile(tmp_path / 'p-disabled-plugin')
    client = authed_client(profile)
    settings = client.get('/api/settings').json()
    settings['web_settings'].setdefault('plugins', {})['auto_translate'] = False
    client.put('/api/settings', json={
        'channels': settings['channels'],
        'web_settings': settings['web_settings'],
    })

    response = client.post('/api/messages/plugin-off-1/translate', json={
        'user_id': 'u@lid',
        'content': 'ສະບາຍດີ',
    })

    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'auto_translate_disabled'
    assert called is False


def test_unknown_text_is_sent_to_ai_instead_of_silently_skipped(monkeypatch, tmp_path):
    from whatsapp_chat_system.rewriter import RewriteResult
    from whatsapp_chat_system import web_api

    seen = []

    class TranslationWorker:
        def translate_to_zh_result(self, text, source_lang):
            seen.append((text, source_lang))
            return RewriteResult(language='Chinese', message='你好', used_fallback=False, error=None)

    monkeypatch.setattr(web_api, '_translation_worker', lambda config: TranslationWorker())
    profile = create_profile(tmp_path / 'p-unknown-text')
    client = authed_client(profile)

    response = client.post('/api/messages/unknown-1/translate', json={
        'user_id': 'u@lid',
        'content': '🙂',
    })

    assert response.status_code == 200
    assert response.json()['translated'] == '你好'
    assert seen == [('🙂', 'Unknown')]


def test_translation_worker_uses_runtime_ai_settings(monkeypatch, tmp_path):
    from whatsapp_chat_system import web_api
    from whatsapp_chat_system.config import AppConfig
    from whatsapp_chat_system.db import Base, create_engine
    from whatsapp_chat_system.settings import AISettings

    db_path = tmp_path / 'runtime-worker.db'
    monkeypatch.setenv('DATABASE_URL', f'sqlite+pysqlite:///{db_path}')
    Base.metadata.create_all(create_engine())
    manager = web_api.setup_ai_runtime_settings(AISettings())
    manager.save_to_db(
        base_url='https://runtime.example/v1',
        default_model='runtime-model',
        api_key='runtime-secret',
    )
    config = AppConfig.from_profile(create_profile(tmp_path / 'p-runtime-worker'))

    worker = web_api._translation_worker(config)
    provider = worker.ai_service.provider
    effective_api_key = getattr(provider, '_effective_api_key')
    effective_base_url = getattr(provider, '_effective_base_url')

    assert effective_api_key() == 'runtime-secret'
    assert effective_base_url() == 'https://runtime.example/v1'


def test_ai_settings_reports_auto_translate_readiness(tmp_path):
    profile = create_profile(tmp_path / 'p-ai-readiness')
    client = authed_client(profile)

    body = client.get('/api/v1/ai/settings').json()

    assert body['auto_translate']['plugin_enabled'] is True
    assert body['auto_translate']['setting_enabled'] is True
    assert body['auto_translate']['ai_configured'] is False
    assert body['auto_translate']['ready'] is False
    assert body['auto_translate']['blocked_reason'] == 'ai_not_configured'
