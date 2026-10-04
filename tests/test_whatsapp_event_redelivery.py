from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from whatsapp_chat_system.db.base import Base
from whatsapp_chat_system.db.models import WhatsAppAccount, WhatsAppEvent
from whatsapp_chat_system.events.whatsapp import (
    WhatsAppEventEnvelope,
    WhatsAppEventService,
)


def _message_envelope(*, sequence: int, occurred_at: datetime) -> WhatsAppEventEnvelope:
    return WhatsAppEventEnvelope(
        event_id="stable-message-event",
        event_type="message.upsert",
        account_id="account-a",
        occurred_at=occurred_at,
        sequence=sequence,
        payload={
            "schema_version": 1,
            "wa_message_id": "WA-STABLE-1",
            "remote_jid": "85620@s.whatsapp.net",
            "sender_jid": "85620@s.whatsapp.net",
            "participant_jid": None,
            "from_me": False,
            "conversation_type": "dm",
            "message_type": "text",
            "timestamp": "2026-09-12T00:00:00Z",
            "text": "same business payload",
            "push_name": "Customer",
            "quoted_wa_message_id": None,
            "media": None,
        },
    )


def test_same_stable_event_id_allows_redelivery_metadata_to_change() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    first_at = datetime(2026, 9, 12, 0, 0, tzinfo=UTC)

    with factory() as db:
        db.add(
            WhatsAppAccount(
                id="account-a",
                name="A",
                session_ref="account:account-a",
            )
        )
        db.commit()

    with factory() as db:
        assert (
            WhatsAppEventService(db).process(
                _message_envelope(sequence=1, occurred_at=first_at)
            )
            is False
        )
        db.commit()

    with factory() as db:
        assert (
            WhatsAppEventService(db).process(
                _message_envelope(
                    sequence=99,
                    occurred_at=first_at + timedelta(seconds=30),
                )
            )
            is True
        )
        db.commit()
        stored = db.scalars(select(WhatsAppEvent)).all()
        assert len(stored) == 1
        assert stored[0].sequence == 1

    engine.dispose()
