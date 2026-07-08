from fastapi.testclient import TestClient

from whatsapp_chat_system.web_api import build_app

from conftest import create_profile, seed_conversation


PASSWORD = 'test-pass'


def authed_client(profile):
    client = TestClient(build_app(str(profile)))
    token = client.post('/api/login', json={'password': PASSWORD}).json()['session_token']
    client.headers.update({'x-session-token': token})
    return client


def test_conversations_pagination_defaults(tmp_path):
    profile = create_profile(tmp_path / 'p')
    for i in range(3):
        seed_conversation(
            profile,
            user_id=f'u{i}@lid',
            user_name=f'User {i}',
            session_id=f's{i}',
            messages=[('user', f'hi {i}', 1700000000.0 + i)],
        )
    client = authed_client(profile)
    resp = client.get('/api/conversations')
    body = resp.json()
    assert body['page'] == 1
    assert body['page_size'] == 50
    assert body['total'] == 3
    assert body['has_more'] is False
    assert len(body['items']) == 3


def test_conversations_pagination_small_page(tmp_path):
    profile = create_profile(tmp_path / 'p')
    for i in range(5):
        seed_conversation(
            profile,
            user_id=f'u{i}@lid',
            user_name=f'User {i}',
            session_id=f's{i}',
            messages=[('user', f'hi {i}', 1700000000.0 + i)],
        )
    client = authed_client(profile)
    p1 = client.get('/api/conversations?page=1&page_size=2').json()
    p2 = client.get('/api/conversations?page=2&page_size=2').json()
    p3 = client.get('/api/conversations?page=3&page_size=2').json()
    assert len(p1['items']) == 2
    assert len(p2['items']) == 2
    assert len(p3['items']) == 1
    assert p1['has_more'] is True
    assert p3['has_more'] is False
    assert p1['items'][0]['user_id'] != p2['items'][0]['user_id']


def test_conversation_detail_pagination(tmp_path):
    profile = create_profile(tmp_path / 'p')
    msgs = []
    for i in range(7):
        msgs.append(('user' if i % 2 == 0 else 'assistant', f'm{i}', 1700000000.0 + i))
    seed_conversation(
        profile,
        user_id='u@lid',
        user_name='User',
        session_id='s',
        messages=msgs,
    )
    client = authed_client(profile)
    p1 = client.get('/api/conversations/u@lid?page=1&page_size=3').json()
    assert p1['total_messages'] == 7
    assert p1['has_more'] is True
    assert len(p1['messages']) == 3
    p3 = client.get('/api/conversations/u@lid?page=3&page_size=3').json()
    assert p3['has_more'] is False
    assert len(p3['messages']) == 1
