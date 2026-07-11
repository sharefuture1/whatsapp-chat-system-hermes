from __future__ import annotations


from whatsapp_chat_system.storage import StateDB
from conftest import create_profile, seed_conversation


def test_incremental_messages_follow_id_cursor_even_when_timestamps_are_out_of_order(tmp_path):
    profile = create_profile(tmp_path / 'cursor-profile')
    seed_conversation(
        profile,
        user_id='cursor@lid',
        user_name='Cursor User',
        session_id='cursor-session',
        messages=[
            ('user', 'id-1-late-time', 100.0),
            ('user', 'id-2-early-time', 1.0),
            ('assistant', 'id-3-middle-time', 2.0),
        ],
    )
    db = StateDB(profile / 'state.db')

    first = db.fetch_user_messages_after('cursor@lid', 0, 1)
    second = db.fetch_user_messages_after('cursor@lid', int(first[-1]['message_id']), 1)
    third = db.fetch_user_messages_after('cursor@lid', int(second[-1]['message_id']), 1)

    assert [int(first[0]['message_id']), int(second[0]['message_id']), int(third[0]['message_id'])] == [1, 2, 3]


def test_incremental_api_exposes_stable_next_cursor_and_has_more(tmp_path):
    from fastapi.testclient import TestClient
    from whatsapp_chat_system.web_api import build_app

    profile = create_profile(tmp_path / 'cursor-api')
    seed_conversation(
        profile,
        user_id='cursor-api@lid',
        user_name='Cursor API',
        session_id='cursor-api-session',
        messages=[('user', f'message-{idx}', float(100 - idx)) for idx in range(4)],
    )
    client = TestClient(build_app(str(profile)))
    token = client.post('/api/login', json={'password': 'test-pass'}).json()['session_token']
    client.headers.update({'x-session-token': token})

    first = client.get('/api/conversations/cursor-api@lid/messages?after_id=0&limit=2')
    assert first.status_code == 200
    body = first.json()
    assert [item['message_id'] for item in body['messages']] == [1, 2]
    assert body['next_after_id'] == 2
    assert body['has_more'] is True

    second = client.get(f"/api/conversations/cursor-api@lid/messages?after_id={body['next_after_id']}&limit=2")
    assert second.status_code == 200
    second_body = second.json()
    assert [item['message_id'] for item in second_body['messages']] == [3, 4]
    assert second_body['next_after_id'] == 4
    assert second_body['has_more'] is False
