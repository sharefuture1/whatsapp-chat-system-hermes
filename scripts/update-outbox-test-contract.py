from __future__ import annotations

import re
from pathlib import Path


path = Path("tests/test_accounts_api.py")
text = path.read_text(encoding="utf-8")
text = text.replace(
    """    def send(self, account_id, *, chat_id, text):
        self.calls.append(('send', account_id, chat_id, text))
        return {'success': True, 'message_id': 'wa-real-1'}
""",
    """    def send(self, account_id, *, chat_id, text, idempotency_key=None):
        self.calls.append(('send', account_id, chat_id, text, idempotency_key))
        return {'success': True, 'message_id': 'wa-real-1'}
""",
)
pattern = re.compile(
    r"def test_v2_reply_uses_own_account_and_persists_outbound_message\(api\):.*?\n\n\ndef test_create_bridge_failure_compensates_database_row",
    re.S,
)
replacement = '''def test_v2_reply_queues_then_worker_sends_and_persists_outbound_message(api):
    from whatsapp_chat_system.db.models import (
        Contact,
        Conversation,
        Message,
        OutboxMessage,
    )
    from whatsapp_chat_system.outbox import OutboxDispatcher

    client, bridge, factory = api
    account = create_account(client, 'WA2')
    with factory() as db:
        contact = Contact(
            account_id=account['id'],
            remote_jid='person@lid',
            display_name='Person',
        )
        db.add(contact)
        db.flush()
        conversation = Conversation(
            account_id=account['id'],
            contact_id=contact.id,
            remote_jid='person@lid',
        )
        db.add(conversation)
        db.commit()
        conversation_id = conversation.id

    response = client.post(
        f'/api/v1/conversations/{conversation_id}/reply',
        json={'message': 'hello', 'idempotency_key': 'client-msg-1'},
    )

    assert response.status_code == 202
    body = response.json()
    assert body['success'] is True
    assert body['queued'] is True
    assert body['message_id'] is None
    assert body['local_message_id']
    assert body['outbox_id']
    assert not any(call[0] == 'send' for call in bridge.calls)

    duplicate = client.post(
        f'/api/v1/conversations/{conversation_id}/reply',
        json={'message': 'hello', 'idempotency_key': 'client-msg-1'},
    )
    assert duplicate.status_code == 202
    assert duplicate.json()['created'] is False
    assert duplicate.json()['local_message_id'] == body['local_message_id']

    with factory() as db:
        row = db.get(Message, body['local_message_id'])
        outbox = db.get(OutboxMessage, body['outbox_id'])
        assert row.account_id == account['id']
        assert row.conversation_id == conversation_id
        assert row.direction == 'outbound'
        assert row.status == 'queued'
        assert row.wa_message_id is None
        assert row.content == 'hello'
        assert outbox.status == 'pending'
        assert outbox.message_id == row.id

    assert OutboxDispatcher(factory, bridge).run_once() == 1
    assert (
        'send',
        account['id'],
        'person@lid',
        'hello',
        'reply:client-msg-1',
    ) in bridge.calls
    with factory() as db:
        row = db.get(Message, body['local_message_id'])
        outbox = db.get(OutboxMessage, body['outbox_id'])
        assert row.status == 'sent'
        assert row.wa_message_id == 'wa-real-1'
        assert outbox.status == 'completed'


def test_create_bridge_failure_compensates_database_row'''
text, count = pattern.subn(replacement, text, count=1)
if count != 1:
    raise RuntimeError("reply contract test patch target missing")
path.write_text(text, encoding="utf-8")
Path(__file__).unlink()
