from fastapi.testclient import TestClient

from whatsapp_chat_system.web_api import build_app

from whatsapp_chat_system.constants import DEFAULT_ADMIN_IDS

from conftest import create_profile, seed_conversation


PASSWORD = 'test-pass'


def authed_client(profile):
    client = TestClient(build_app(str(profile)))
    token = client.post('/api/login', json={'password': PASSWORD}).json()['session_token']
    client.headers.update({'x-session-token': token})
    return client


def test_search_finds_message(tmp_path):
    profile = create_profile(tmp_path / 'p')
    seed_conversation(
        profile,
        user_id='u@lid',
        user_name='User',
        session_id='s',
        messages=[
            ('user', '今天天气真好', 1700000000.0),
            ('assistant', '是啊', 1700000001.0),
            ('user', '我去吃饭', 1700000002.0),
        ],
    )
    client = authed_client(profile)
    resp = client.get('/api/search?q=天气')
    assert resp.status_code == 200
    body = resp.json()
    assert body['q'] == '天气'
    assert len(body['results']) == 1
    assert body['results'][0]['user_id'] == 'u@lid'
    assert '天气' in body['results'][0]['content']


def test_search_skips_hidden_messages(tmp_path):
    profile = create_profile(tmp_path / 'p')
    seed_conversation(
        profile,
        user_id='u@lid',
        user_name='User',
        session_id='s',
        messages=[('user', 'secret needle here', 1700000000.0), ('user', 'other text', 1700000001.0)],
    )
    client = authed_client(profile)
    detail = client.get('/api/conversations/u@lid?page=1&page_size=10').json()
    secret_mid = next(m['message_id'] for m in detail['messages'] if 'secret' in m['content'])
    client.post('/api/messages/hide', json={'message_ids': [secret_mid]})
    resp = client.get('/api/search?q=secret')
    body = resp.json()
    assert body['results'] == []


def test_search_skips_admin_users(tmp_path):
    profile = create_profile(tmp_path / 'p')
    admin_id = next(iter(DEFAULT_ADMIN_IDS))
    seed_conversation(
        profile,
        user_id=admin_id,
        user_name='Admin',
        session_id='s',
        messages=[('user', 'admin secret', 1700000000.0)],
    )
    client = authed_client(profile)
    resp = client.get('/api/search?q=secret')
    assert resp.json()['results'] == []


def test_search_empty_query(tmp_path):
    profile = create_profile(tmp_path / 'p')
    client = authed_client(profile)
    resp = client.get('/api/search?q=')
    assert resp.json() == {'q': '', 'results': []}
