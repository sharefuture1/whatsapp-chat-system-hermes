from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import create_engine

from whatsapp_chat_system.ai.auto_reply_reconciler import AutoReplyReconciler
from whatsapp_chat_system.db import Base, create_session_factory
from whatsapp_chat_system.db.models import AnalysisJob, Contact, Conversation, Message, WhatsAppAccount


def _id() -> str:
    return str(uuid4())


def test_auto_reply_reconciler_enqueues_unreplied_inbound_message(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path/'reconcile.db'}")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    now = datetime.now(timezone.utc)

    with factory() as session:
        account = WhatsAppAccount(id=_id(), name='acct', status='online', session_ref='account:test', enabled=True, auto_reply_mode='auto')
        contact = Contact(id=_id(), account_id=account.id, remote_jid='123@lid')
        conversation = Conversation(id=_id(), account_id=account.id, contact_id=contact.id, remote_jid='123@lid', ai_mode='auto')
        inbound = Message(
            id=_id(),
            account_id=account.id,
            conversation_id=conversation.id,
            contact_id=contact.id,
            wa_message_id='wamid-1',
            direction='inbound',
            message_type='text',
            content='你好',
            status='received',
            occurred_at=now - timedelta(minutes=5),
        )
        session.add_all([account, contact, conversation, inbound])
        session.commit()

    reconciler = AutoReplyReconciler(factory)
    assert reconciler.run_once() is True

    with factory() as session:
        jobs = session.query(AnalysisJob).all()
        assert len(jobs) == 1
        assert jobs[0].job_type == 'auto_reply'
        assert jobs[0].conversation_id == conversation.id


def test_auto_reply_reconciler_skips_when_outbound_already_exists(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path/'reconcile-skip.db'}")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    now = datetime.now(timezone.utc)

    with factory() as session:
        account = WhatsAppAccount(id=_id(), name='acct', status='online', session_ref='account:test', enabled=True, auto_reply_mode='auto')
        contact = Contact(id=_id(), account_id=account.id, remote_jid='123@lid')
        conversation = Conversation(id=_id(), account_id=account.id, contact_id=contact.id, remote_jid='123@lid', ai_mode='auto')
        inbound = Message(
            id=_id(),
            account_id=account.id,
            conversation_id=conversation.id,
            contact_id=contact.id,
            wa_message_id='wamid-1',
            direction='inbound',
            message_type='text',
            content='hello',
            status='received',
            occurred_at=now - timedelta(minutes=5),
        )
        outbound = Message(
            id=_id(),
            account_id=account.id,
            conversation_id=conversation.id,
            contact_id=contact.id,
            wa_message_id='wamid-2',
            direction='outbound',
            message_type='text',
            content='reply',
            status='sent',
            occurred_at=now - timedelta(minutes=4),
        )
        session.add_all([account, contact, conversation, inbound, outbound])
        session.commit()

    reconciler = AutoReplyReconciler(factory)
    assert reconciler.run_once() is False

    with factory() as session:
        assert session.query(AnalysisJob).count() == 0
