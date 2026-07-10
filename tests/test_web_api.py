from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from whatsapp_chat_system.web_api import build_app
from conftest import create_profile, seed_conversation


PASSWORD = 'test-pass'


def authed_client(profile):
    client = TestClient(build_app(str(profile)))
    resp = client.post('/api/login', json={'password': PASSWORD})
    token = resp.json()['session_token']
    client.headers.update({'x-session-token': token})
    return client


def test_cors_preflight_bypasses_session_auth(tmp_path):
    profile = create_profile(tmp_path / 'p-cors')
    client = TestClient(build_app(str(profile)))
    resp = client.options(
        '/api/settings',
        headers={
            'Origin': 'https://example.vercel.app',
            'Access-Control-Request-Method': 'PUT',
            'Access-Control-Request-Headers': 'content-type,x-session-token',
        },
    )
    assert resp.status_code in {200, 204}
    assert resp.headers.get('access-control-allow-origin') == '*'
    assert 'PUT' in resp.headers.get('access-control-allow-methods', '')
    assert client.get('/api/settings').status_code == 401


def test_schedule_delete_missing_returns_404(tmp_path):
    profile = create_profile(tmp_path / 'p-schedule-delete')
    client = authed_client(profile)
    assert client.delete('/api/schedule/not-found').status_code == 404


def test_settings_exposes_model_default_and_plugins(tmp_path):
    profile = create_profile(tmp_path / 'p-settings-meta')
    client = authed_client(profile)
    resp = client.get('/api/settings')
    assert resp.status_code == 200
    body = resp.json()
    assert body['model'] == {
        'provider': 'wendingai',
        'default': 'gpt-5.3-codex-spark',
        'base_url': 'https://wendingai.future1.us/v1',
        'api_key_configured': False,
        'effective_model': 'gpt-5.3-codex-spark',
        'model_source': 'global_default',
    }
    assert 'unit-test-secret' not in json.dumps(body)
    assert 'plugins' in body
    assert isinstance(body['plugins'], dict)
    assert 'auto_translate' in body['plugins']


def test_ai_settings_v1_is_safe_and_reports_effective_account_model(monkeypatch, tmp_path):
    monkeypatch.setenv('WENDING_AI_API_KEY', 'unit-test-secret')
    monkeypatch.setenv('WENDING_AI_DEFAULT_MODEL', 'env-global-model')
    profile = create_profile(tmp_path / 'p-ai-settings-v1')
    settings_path = profile / 'web-settings.json'
    stored = json.loads(settings_path.read_text())
    stored['reply']['ai_model'] = 'account-model'
    settings_path.write_text(json.dumps(stored))
    client = authed_client(profile)

    response = client.get('/api/v1/ai/settings')

    assert response.status_code == 200
    assert response.json() == {
        'provider': 'wendingai',
        'base_url': 'https://wendingai.future1.us/v1',
        'default_model': 'env-global-model',
        'timeout_seconds': 90,
        'max_retries': 2,
        'api_key_configured': True,
        'account_model': 'account-model',
        'effective_model': 'account-model',
        'model_source': 'account_profile',
    }
    assert 'unit-test-secret' not in response.text


def test_reply_preview_ai_fallback_is_structured_failure(monkeypatch, tmp_path):
    from whatsapp_chat_system.rewriter import RewriteResult
    from whatsapp_chat_system.router import AdminRouter

    profile = create_profile(tmp_path / 'p-ai-preview-failure')

    def failed_preview(self, target_text, message, mode='direct'):
        return {
            'target': {'id': target_text, 'name': 'User'},
            'rewrite': RewriteResult(
                language='Thai',
                message=message,
                used_fallback=True,
                error={'code': 'timeout', 'retryable': True, 'request_id': 'req_timeout'},
            ),
            'memory_markdown': '',
            'profile_sidecar': {},
            'reply_overrides': {},
        }

    monkeypatch.setattr(AdminRouter, 'prepare_reply', failed_preview)
    client = authed_client(profile)
    response = client.post('/api/reply', json={
        'target': 'u@lid',
        'message': 'fallback text',
        'mode': 'smart',
        'preview_only': True,
    })

    assert response.status_code == 200
    body = response.json()
    assert body['success'] is False
    assert body['preview_only'] is True
    assert body['rewrite']['message'] == 'fallback text'
    assert body['rewrite']['used_fallback'] is True
    assert body['error'] == {'code': 'timeout', 'retryable': True, 'request_id': 'req_timeout'}


def test_reply_preview_refused_when_quick_reply_plugin_off(tmp_path):
    from fastapi.testclient import TestClient
    from whatsapp_chat_system.web_api import build_app

    profile = create_profile(tmp_path / 'p-plugin-qr')
    settings = profile / 'web-settings.json'
    data = json.loads(settings.read_text())
    data.setdefault('plugins', {})['quick_reply'] = False
    settings.write_text(json.dumps(data))
    client = TestClient(build_app(str(profile)))
    token = client.post('/api/login', json={'password': 'test-pass'}).json()['session_token']
    client.headers.update({'x-session-token': token})
    resp = client.post('/api/reply', json={
        'target': 'demo@lid',
        'message': 'hi',
        'mode': 'smart',
        'preview_only': True,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body.get('success') is False
    assert body.get('plugin') == 'quick_reply'


def test_health_with_isolated_profile(tmp_path):
    profile = create_profile(tmp_path / 'p1')
    client = TestClient(build_app(str(profile)))
    resp = client.get('/api/health')
    assert resp.status_code == 200
    assert resp.json()['profile'].endswith('p1')


def test_login_endpoint(tmp_path):
    profile = create_profile(tmp_path / 'p2')
    client = TestClient(build_app(str(profile)))
    resp = client.post('/api/login', json={'password': PASSWORD})
    assert resp.status_code == 200
    body = resp.json()
    assert body['success'] is True
    assert body['session_token']
    assert body['expires_in'] > 0


def test_login_wrong_password_is_401(tmp_path):
    profile = create_profile(tmp_path / 'p3')
    client = TestClient(build_app(str(profile)))
    resp = client.post('/api/login', json={'password': 'wrong'})
    assert resp.status_code == 401


def test_settings_endpoint(tmp_path):
    profile = create_profile(tmp_path / 'p4')
    client = authed_client(profile)
    resp = client.get('/api/settings')
    assert resp.status_code == 200
    body = resp.json()
    assert 'channels' in body
    assert 'web_settings' in body
    assert 'auth' not in body['web_settings']
    assert 'sessions' not in body['web_settings']


def test_dashboard_with_conversation(tmp_path):
    profile = create_profile(tmp_path / 'p5')
    seed_conversation(
        profile,
        user_id='u5@lid',
        user_name='User Five',
        session_id='s5',
        messages=[('user', 'hello', 1700000000.0), ('assistant', 'hi there', 1700000001.0)],
    )
    client = authed_client(profile)
    resp = client.get('/api/dashboard')
    assert resp.status_code == 200
    body = resp.json()
    assert body['stats']['total_conversations'] == 1
    assert body['stats']['total_messages'] == 2


def test_reply_preview_only_does_not_send(tmp_path):
    profile = create_profile(tmp_path / 'p6')
    seed_conversation(
        profile,
        user_id='u6@lid',
        user_name='User Six',
        session_id='s6',
        messages=[('user', 'hi', 1700000010.0)],
    )
    client = authed_client(profile)
    resp = client.post('/api/reply', json={
        'target': 'u6@lid',
        'message': '你好，今天怎么样？',
        'mode': 'smart',
        'preview_only': True,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body['preview_only'] is True
    assert 'rewrite' in body


def test_logout_invalidates_session(tmp_path):
    profile = create_profile(tmp_path / 'p7')
    client = authed_client(profile)
    client.post('/api/logout')
    denied = client.get('/api/settings')
    assert denied.status_code == 401


def test_rate_limit_blocks_after_repeated_failures(tmp_path):
    profile = create_profile(tmp_path / 'p8')
    client = TestClient(build_app(str(profile)))
    statuses = []
    for _ in range(6):
        resp = client.post('/api/login', json={'password': 'wrong-password'})
        statuses.append(resp.status_code)
    assert statuses[-1] == 429


def test_hide_messages_round_trip(tmp_path):
    profile = create_profile(tmp_path / 'p')
    seed_conversation(
        profile,
        user_id='u9@lid',
        user_name='User Nine',
        session_id='s9',
        messages=[('user', 'm1', 1700000020.0), ('assistant', 'r1', 1700000021.0)],
    )
    client = authed_client(profile)
    settings = client.get('/api/settings').json()
    settings['web_settings']['message_ops']['hide_messages_enabled'] = True
    client.put('/api/settings', json={'channels': settings['channels'], 'web_settings': settings['web_settings']})
    detail = client.get('/api/conversations/u9@lid?page=1&page_size=10').json()
    msg_id = detail['messages'][1]['message_id']  # oldest of the two
    hide = client.post('/api/messages/hide', json={'message_ids': [msg_id]})
    assert hide.status_code == 200
    detail2 = client.get('/api/conversations/u9@lid?page=1&page_size=10').json()
    target = next(m for m in detail2['messages'] if m['message_id'] == msg_id)
    assert target['hidden'] is True


def test_hide_messages_rejected_when_feature_disabled(tmp_path):
    profile = create_profile(tmp_path / 'p-disabled')
    seed_conversation(
        profile,
        user_id='u10@lid',
        user_name='User Ten',
        session_id='s10',
        messages=[('user', 'm1', 1700000030.0)],
    )
    client = authed_client(profile)
    detail = client.get('/api/conversations/u10@lid?page=1&page_size=10').json()
    msg_id = detail['messages'][0]['message_id']
    hide = client.post('/api/messages/hide', json={'message_ids': [msg_id]})
    assert hide.status_code == 403
    assert hide.json()['detail'] == 'Message hiding is disabled'


def test_hidden_message_ids_ignored_when_feature_disabled(tmp_path):
    profile = create_profile(tmp_path / 'p-ignored')
    seed_conversation(
        profile,
        user_id='u11@lid',
        user_name='User Eleven',
        session_id='s11',
        messages=[
            ('user', 'needle one', 1700000040.0),
            ('assistant', 'reply one', 1700000041.0),
        ],
    )
    client = authed_client(profile)
    detail = client.get('/api/conversations/u11@lid?page=1&page_size=10').json()
    hidden_id = detail['messages'][1]['message_id']

    settings = client.get('/api/settings').json()
    settings['web_settings']['hidden_message_ids'] = [hidden_id]
    client.put('/api/settings', json={'channels': settings['channels'], 'web_settings': settings['web_settings']})

    detail2 = client.get('/api/conversations/u11@lid?page=1&page_size=10').json()
    target = next(m for m in detail2['messages'] if m['message_id'] == hidden_id)
    assert target['hidden'] is False
    assert detail2['hidden_message_count'] == 0
    assert detail2['visible_message_count'] == 2

    delta = client.get('/api/conversations/u11@lid/messages?after_id=0&limit=10').json()
    delta_target = next(m for m in delta['messages'] if m['message_id'] == hidden_id)
    assert delta_target['hidden'] is False
    assert delta['count'] == 2

    search = client.get('/api/search?q=needle').json()
    assert len(search['results']) == 1
    assert search['results'][0]['message_id'] == hidden_id


def test_built_frontend_is_served_from_root(tmp_path):
    profile = create_profile(tmp_path / 'p-web')
    web_dist = tmp_path / 'dist'
    web_dist.mkdir()
    (web_dist / 'index.html').write_text('<!doctype html><html><body><div id="root">console</div></body></html>')

    client = TestClient(build_app(str(profile), web_dist=web_dist))

    root = client.get('/')
    assert root.status_code == 200
    assert 'console' in root.text

    nested = client.get('/chats/123')
    assert nested.status_code == 200
    assert 'console' in nested.text


def test_missing_frontend_dist_does_not_mount_root(tmp_path):
    profile = create_profile(tmp_path / 'p-no-web')
    missing = Path(tmp_path / 'missing-dist')

    client = TestClient(build_app(str(profile), web_dist=missing))
    root = client.get('/')

    assert root.status_code == 404


def test_settings_can_store_ai_model_and_user_overrides(tmp_path):
    profile = create_profile(tmp_path / 'p-settings-ai')
    client = authed_client(profile)
    settings = client.get('/api/settings').json()
    settings['web_settings']['reply']['ai_model'] = 'gpt-5.3-codex-spark'
    settings['web_settings']['reply']['custom_system_prompt'] = 'Always be concise.'
    settings['web_settings']['reply']['default_reply_style'] = 'Warm and short.'
    settings['web_settings']['reply']['user_overrides'] = {
        'u-special@lid': {
            'ai_model': 'custom-model-x',
            'custom_system_prompt': 'Be gentler with this user.',
            'reply_style': 'Empathetic and intimate.',
        }
    }
    resp = client.put('/api/settings', json={'channels': settings['channels'], 'web_settings': settings['web_settings']})
    assert resp.status_code == 200

    fresh = client.get('/api/settings').json()
    reply = fresh['web_settings']['reply']
    assert reply['ai_model'] == 'gpt-5.3-codex-spark'
    assert reply['custom_system_prompt'] == 'Always be concise.'
    assert reply['default_reply_style'] == 'Warm and short.'
    assert reply['user_overrides']['u-special@lid']['ai_model'] == 'custom-model-x'
    assert reply['user_overrides']['u-special@lid']['reply_style'] == 'Empathetic and intimate.'
