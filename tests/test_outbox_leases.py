from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from whatsapp_chat_system.db.base import Base
from whatsapp_chat_system.db.models import (
    Contact,
    Conversation,
    Message,
    OutboxMessage,
    WhatsAppAccount,
)
from whatsapp_chat_system.outbox import OutboxDispatcher, enqueue_outbox_message


def _seed_outbox(factory: sessionmaker[Session]) -> tuple[str, str]:
    with factory() as session:
        account = WhatsAppAccount(name="WA", session_ref="sessions/wa")
        session.add(account)
        session.flush()
        contact = Contact(
            account_id=account.id,
            remote_jid="person@lid",
            display_name="Person",
        )
        session.add(contact)
        session.flush()
        conversation = Conversation(
            account_id=account.id,
            contact_id=contact.id,
            remote_jid=contact.remote_jid,
        )
        session.add(conversation)
        session.flush()
        message, outbox, _ = enqueue_outbox_message(
            session,
            conversation,
            text="hello",
            idempotency_key="reply:lease-test",
        )
        session.commit()
        return message.id, outbox.id


def test_stale_worker_does_not_finalize_after_lease_is_stolen(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'outbox.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    message_id, outbox_id = _seed_outbox(factory)

    class LeaseStealingBridge:
        def send(self, _account_id, **_payload):
            with factory() as session:
                outbox = session.get(OutboxMessage, outbox_id)
                outbox.lease_owner = "worker-b"
                session.commit()
            return {"success": True, "message_id": "wa-real-id"}

    dispatcher = OutboxDispatcher(
        factory,
        LeaseStealingBridge(),
        worker_id="worker-a",
    )

    assert dispatcher.run_once() == 1

    with factory() as session:
        outbox = session.get(OutboxMessage, outbox_id)
        message = session.get(Message, message_id)
        assert outbox.status == "claimed"
        assert outbox.lease_owner == "worker-b"
        assert outbox.last_error is None
        assert message.status == "queued"
        assert message.wa_message_id is None

    engine.dispose()


def test_stale_worker_does_not_record_failure_for_another_owner(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'outbox-failure.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    message_id, outbox_id = _seed_outbox(factory)
    dispatcher = OutboxDispatcher(factory, object(), worker_id="worker-a")

    assert dispatcher._claim_batch() == [outbox_id]
    with factory() as session:
        outbox = session.scalar(
            select(OutboxMessage).where(OutboxMessage.id == outbox_id)
        )
        outbox.lease_owner = "worker-b"
        session.commit()

    dispatcher._finalize_failure(
        outbox_id,
        code="bridge_timeout",
        message="timeout",
        retryable=True,
    )

    with factory() as session:
        outbox = session.get(OutboxMessage, outbox_id)
        message = session.get(Message, message_id)
        assert outbox.status == "claimed"
        assert outbox.lease_owner == "worker-b"
        assert outbox.last_error is None
        assert message.status == "queued"
        assert message.error_code is None

    engine.dispose()
