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
