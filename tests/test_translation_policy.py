from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from whatsapp_chat_system.db.base import Base
from whatsapp_chat_system.db.models import TranslationBatch, WhatsAppAccount
from whatsapp_chat_system.events.whatsapp import WhatsAppEventEnvelope, WhatsAppEventService
from whatsapp_chat_system.translation_policy import resolve_auto_translation_policy


def test_effective_policy_requires_plugin_setting_and_ai_and_clamps_window():
    base = {
        "plugins": {"auto_translate": True},
        "message_ops": {
            "auto_translate": True,
            "translation_target_language": "zh-CN",
            "translation_context_window": 99,
        },
    }
    policy = resolve_auto_translation_policy(base, ai_configured=True)
    assert policy.enabled is True
    assert policy.blocked_reason is None
    assert policy.target_lang == "zh-CN"
    assert policy.window_size == 20

    assert (
        resolve_auto_translation_policy(
            {**base, "plugins": {"auto_translate": False}}, ai_configured=True
        ).blocked_reason
        == "plugin_disabled"
    )
    assert (
        resolve_auto_translation_policy(
            {
                **base,
                "message_ops": {
                    **base["message_ops"],
                    "auto_translate": False,
                },
            },
            ai_configured=True,
        ).blocked_reason
        == "setting_disabled"
    )
    assert (
        resolve_auto_translation_policy(base, ai_configured=False).blocked_reason
        == "ai_not_configured"
    )


def _event(account_id: str, event_id: str = "evt-1") -> WhatsAppEventEnvelope:
    return WhatsAppEventEnvelope(
        event_id=event_id,
        event_type="message.upsert",
        account_id=account_id,
        occurred_at=datetime(2026, 9, 12, 7, 0, tzinfo=UTC),
        sequence=1,
        payload={
            "schema_version": 1,
            "wa_message_id": "wa-1",
            "remote_jid": "85620@s.whatsapp.net",
            "sender_jid": "85620@s.whatsapp.net",
            "participant_jid": None,
            "from_me": False,
            "conversation_type": "dm",
            "message_type": "text",
            "timestamp": "2026-09-12T07:00:00Z",
            "text": "hello from customer",
            "push_name": "Customer",
            "quoted_wa_message_id": None,
            "media": None,
        },
    )


def _factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    with factory() as session:
        session.add(
            WhatsAppAccount(
                id="acc-1",
                name="A",
                session_ref="account:acc-1",
                status="online",
                enabled=True,
            )
        )
        session.commit()
    return engine, factory


def test_ingress_does_not_enqueue_translation_when_effective_policy_is_blocked():
    engine, factory = _factory()
    try:
        disabled = resolve_auto_translation_policy(
            {
                "plugins": {"auto_translate": True},
                "message_ops": {"auto_translate": False},
            },
            ai_configured=True,
        )
        with factory() as session:
            service = WhatsAppEventService(
                session, translation_policy_resolver=lambda: disabled
            )
            assert service.process(_event("acc-1")) is False
            session.commit()

        with factory() as session:
            assert session.scalars(select(TranslationBatch)).all() == []
    finally:
        engine.dispose()


def test_ingress_uses_effective_policy_window_and_enqueues_once():
    engine, factory = _factory()
    try:
        enabled = resolve_auto_translation_policy(
            {
                "plugins": {"auto_translate": True},
                "message_ops": {
                    "auto_translate": True,
                    "translation_context_window": 4,
                    "translation_target_language": "zh-CN",
                },
            },
            ai_configured=True,
        )
        with factory() as session:
            service = WhatsAppEventService(
                session, translation_policy_resolver=lambda: enabled
            )
            assert service.process(_event("acc-1")) is False
            session.commit()

        with factory() as session:
            batches = session.scalars(select(TranslationBatch)).all()
            assert len(batches) == 1
            assert batches[0].window_size == 4
            assert batches[0].target_lang == "zh-CN"
    finally:
        engine.dispose()
