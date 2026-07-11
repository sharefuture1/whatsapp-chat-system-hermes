from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from conftest import create_profile, seed_conversation
from whatsapp_chat_system.db.base import Base
from whatsapp_chat_system.db.models import Contact, Conversation, Message, WhatsAppAccount
from whatsapp_chat_system.web_api import build_app


def login(client):
    token = client.post('/api/login', json={'password': 'test-pass'}).json()['session_token']
    client.headers.update({'x-session-token': token})


def test_legacy_deleted_conversation_remains_in_contacts(tmp_path):
    profile = create_profile(tmp_path / 'profile')
    seed_conversation(
        profile, user_id='person@lid', user_name='Person', session_id='session-person',
        messages=[('user', 'history stays', 1700000000.0)],
    )
    client = TestClient(build_app(str(profile)))
    login(client)

    assert client.post('/api/chat/delete', json={'user_id': 'person@lid'}).status_code == 200
    conversations = client.get('/api/conversations').json()['items']
    contacts = client.get('/api/contacts').json()['items']

    assert all(item['user_id'] != 'person@lid' for item in conversations)
    contact = next(item for item in contacts if item['user_id'] == 'person@lid')
    assert contact['conversation_deleted'] is True
    assert contact['last_message'] == 'history stays'


def standalone_client(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'standalone.db'}", connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    profile = create_profile(tmp_path / 'profile')
    client = TestClient(build_app(str(profile), account_session_factory=factory))
    login(client)
    return client, factory, engine


def test_v1_soft_delete_keeps_contact_and_history_then_restore_same_conversation(tmp_path):
    client, factory, engine = standalone_client(tmp_path)
    with factory() as db:
        db.add(WhatsAppAccount(id='account-a', name='A', session_ref='account:a'))
        contact = Contact(account_id='account-a', remote_jid='person@lid', display_name='Person')
        db.add(contact)
        db.flush()
        conversation = Conversation(account_id='account-a', contact_id=contact.id, remote_jid='person@lid')
        db.add(conversation)
        db.flush()
        message = Message(
            account_id='account-a', conversation_id=conversation.id, contact_id=contact.id,
            wa_message_id='WA-1', direction='inbound', message_type='text', content='history',
            status='received', occurred_at=datetime.utcnow(),
        )
        db.add(message)
        db.commit()
        contact_id, conversation_id, message_id = contact.id, conversation.id, message.id

    deleted = client.delete(f'/api/v1/conversations/{conversation_id}')
    assert deleted.status_code == 200
    assert client.get('/api/v1/conversations?account_id=account-a').json()['items'] == []
    contact_item = client.get('/api/v1/contacts?account_id=account-a').json()['items'][0]
    assert contact_item['contact_id'] == contact_id
    assert contact_item['conversation_id'] is None

    with factory() as db:
        assert db.get(Contact, contact_id) is not None
        assert db.get(Message, message_id) is not None
        assert db.get(Conversation, conversation_id).deleted_at is not None

    restored = client.post(f'/api/v1/contacts/{contact_id}/conversation')
    assert restored.status_code == 200
    assert restored.json()['conversation_id'] == conversation_id
    with factory() as db:
        assert db.get(Conversation, conversation_id).deleted_at is None
        assert db.get(Message, message_id) is not None
    engine.dispose()


def test_v1_ensure_creates_empty_conversation_for_contact_without_one(tmp_path):
    client, factory, engine = standalone_client(tmp_path)
    with factory() as db:
        db.add(WhatsAppAccount(id='account-a', name='A', session_ref='account:a'))
        contact = Contact(account_id='account-a', remote_jid='new@lid', display_name='New')
        db.add(contact)
        db.commit()
        contact_id = contact.id

    response = client.post(f'/api/v1/contacts/{contact_id}/conversation')
    assert response.status_code == 200
    body = response.json()
    assert body['account_id'] == 'account-a'
    assert body['remote_jid'] == 'new@lid'
    with factory() as db:
        row = db.scalar(select(Conversation).where(Conversation.contact_id == contact_id))
        assert row.id == body['conversation_id']
        assert row.deleted_at is None
    engine.dispose()
