from fastapi.testclient import TestClient

from whatsapp_chat_system.web_api import build_app


PROFILE = '/root/.hermes/profiles/whatsapp-support'
PASSWORD = 'test?9'


def authed_client():
    client = TestClient(build_app(PROFILE))
    resp = client.post('/api/login', json={'password': PASSWORD})
    token = resp.json()['session_token']
    client.headers.update({'x-session-token': token})
    return client


def test_health_endpoint():
    client = TestClient(build_app(PROFILE))
    resp = client.get('/api/health')
    assert resp.status_code == 200
    assert resp.json()['ok'] is True


def test_login_endpoint():
    client = TestClient(build_app(PROFILE))
    resp = client.post('/api/login', json={'password': PASSWORD})
    assert resp.status_code == 200
    assert resp.json()['success'] is True
    assert resp.json()['session_token']
    assert resp.json()['expires_in'] > 0


def test_settings_endpoint():
    client = authed_client()
    resp = client.get('/api/settings')
    assert resp.status_code == 200
    body = resp.json()
    assert 'channels' in body
    assert 'web_settings' in body


def test_dashboard_endpoint():
    client = authed_client()
    resp = client.get('/api/dashboard')
    assert resp.status_code == 200
    body = resp.json()
    assert 'stats' in body
    assert 'recent_conversations' in body


def test_reply_preview_only_does_not_fail():
    client = authed_client()
    resp = client.post('/api/reply', json={
        'target': '92467156246781@lid',
        'message': '你好，今天怎么样？',
        'mode': 'smart',
        'preview_only': True,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body['preview_only'] is True
    assert 'rewrite' in body


def test_logout_invalidates_session():
    client = authed_client()
    logout_resp = client.post('/api/logout')
    assert logout_resp.status_code == 200
    denied = client.get('/api/settings')
    assert denied.status_code == 401


def test_rate_limit_blocks_after_repeated_failures():
    client = TestClient(build_app(PROFILE))
    statuses = []
    for _ in range(6):
        resp = client.post('/api/login', json={'password': 'wrong-password'})
        statuses.append(resp.status_code)
    assert statuses[-1] == 429
