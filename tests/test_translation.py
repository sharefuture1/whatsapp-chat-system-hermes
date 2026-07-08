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
