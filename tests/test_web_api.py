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
    profile = create_profile(tmp_path / 'p9')
    seed_conversation(
        profile,
        user_id='u9@lid',
        user_name='User Nine',
        session_id='s9',
        messages=[('user', 'm1', 1700000020.0), ('assistant', 'r1', 1700000021.0)],
    )
    client = authed_client(profile)
    detail = client.get('/api/conversations/u9@lid').json()
    msg_id = detail['messages'][0]['message_id']
    hide = client.post('/api/messages/hide', json={'message_ids': [msg_id]})
    assert hide.status_code == 200
    detail2 = client.get('/api/conversations/u9@lid').json()
    target = next(m for m in detail2['messages'] if m['message_id'] == msg_id)
    assert target['hidden'] is True
