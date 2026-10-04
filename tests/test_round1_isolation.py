"""Round 1 real API/ORM regressions; no network calls or WhatsApp sends."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from sqlalchemy import select

from test_standalone_p0_security import (
    ADMIN_PASSWORD,
    _login,
    _seed_conversations,
    security_api as security_api,
)
from whatsapp_chat_system.db.models import (
    Conversation,
    Message,
    MessageTranslation,
    TranslationBatch,
    WhatsAppAccount,
)
from whatsapp_chat_system.events.inbound_translation import (
    enqueue_for_inbound_translation,
    source_text_hash,
)
from whatsapp_chat_system.translations_dispatcher import TranslationDispatcher


def _seed_memory(
    factory, *, same_account=False, existing_failed=False, content="Hello"
):
    ids = _seed_conversations(factory)
    with factory() as session:
        message = session.get(Message, ids["allowed_message"])
        message.content = content
        message.occurred_at = datetime.now(timezone.utc)
        source = session.get(Message, ids["foreign_message"])
        source.content = content
        source_hash = hashlib.sha256(content.encode()).hexdigest()
        if same_account:
            source.account_id = message.account_id
            source.conversation_id = message.conversation_id
            source.contact_id = message.contact_id
        session.add(
            MessageTranslation(
                account_id=source.account_id,
                conversation_id=source.conversation_id,
                message_id=source.id,
                target_lang="zh-CN",
                source_text=content,
                source_text_hash=source_hash,
                translated_text="正确译文",
                source_lang="Latin",
                status="completed",
                context_window_size=1,
            )
        )
        if existing_failed:
            session.add(
                MessageTranslation(
                    account_id=message.account_id,
                    conversation_id=message.conversation_id,
                    message_id=message.id,
                    target_lang="zh-CN",
                    source_text_hash=source_hash,
                    status="failed",
                    error_code="old_failure",
                )
            )
        session.commit()
    return ids


def test_sec_auth_015_login_does_not_clear_force_change(security_api):
    client, app, _ = security_api
    _login(client)
    app.state.runtime.web_settings["users"]["admin"]["password_change_required"] = True
    token = _login(client)
    headers = {"x-session-token": token}
    assert (
        app.state.runtime.web_settings["users"]["admin"]["password_change_required"]
        is True
    )
    me = client.get("/api/v1/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["password_change_required"] is True
    blocked = client.get("/api/v1/accounts", headers=headers)
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "password_change_required"


def test_sec_auth_015_successful_change_revokes_current_session(security_api):
    client, app, _ = security_api
    token = _login(client)
    app.state.runtime.web_settings["users"]["admin"]["password_change_required"] = True
    response = client.post(
        "/api/v1/users/change-password",
        headers={"x-session-token": token},
        json={
            "old_password": ADMIN_PASSWORD,
            "new_password": "new-round1-safe-password",
        },
    )
    assert response.status_code == 200
    assert not app.state.runtime.web_settings["users"]["admin"].get(
        "password_change_required"
    )
    assert (
        client.get("/api/v1/me", headers={"x-session-token": token}).status_code == 401
    )
    fresh = client.post(
        "/api/login", json={"username": "admin", "password": "new-round1-safe-password"}
    )
    assert fresh.status_code == 200
    assert (
        client.get(
            "/api/v1/accounts",
            headers={"x-session-token": fresh.json()["session_token"]},
        ).status_code
        == 200
    )


def test_sec_auth_015_wrong_password_keeps_restriction(security_api):
    client, app, _ = security_api
    token = _login(client)
    app.state.runtime.web_settings["users"]["admin"]["password_change_required"] = True
    response = client.post(
        "/api/v1/users/change-password",
        headers={"x-session-token": token},
        json={"old_password": "wrong", "new_password": "new-round1-safe-password"},
    )
    assert response.status_code == 403
    assert (
        app.state.runtime.web_settings["users"]["admin"]["password_change_required"]
        is True
    )
    assert (
        client.get("/api/v1/accounts", headers={"x-session-token": token}).status_code
        == 403
    )


def test_data_004_inbound_does_not_reuse_foreign_account_memory(security_api):
    _, _, factory = security_api
    ids = _seed_memory(factory)
    with factory() as session:
        batch = enqueue_for_inbound_translation(
            session,
            session.get(WhatsAppAccount, ids["allowed_account"]),
            session.get(Conversation, ids["allowed_conversation"]),
            session.get(Message, ids["allowed_message"]),
        )
        assert batch is not None
        assert (
            session.scalar(
                select(MessageTranslation).where(
                    MessageTranslation.message_id == ids["allowed_message"]
                )
            )
            is None
        )


def test_data_004_dispatcher_does_not_reuse_foreign_account_memory(security_api):
    _, _, factory = security_api
    ids = _seed_memory(factory)
    with factory() as session:
        message = session.get(Message, ids["allowed_message"])
        batch = TranslationBatch(
            account_id=message.account_id,
            conversation_id=message.conversation_id,
            anchor_message_id=message.id,
            target_lang="zh-CN",
            window_size=1,
        )
        session.add(batch)
        session.flush()
        plan = TranslationDispatcher(factory, None)._build_plan(
            session, batch, [message]
        )
        assert len(plan.items) == 1


def test_data_004_batch_endpoint_does_not_reuse_foreign_account_memory(security_api):
    client, _, factory = security_api
    ids = _seed_memory(factory)
    response = client.post(
        f"/api/v1/conversations/{ids['allowed_conversation']}/translations",
        headers={"x-session-token": _login(client)},
        json={"anchor_message_id": ids["allowed_message"], "window_size": 1},
    )
    assert response.status_code == 202
    assert response.json()["batch_id"] is not None
    assert response.json()["cached_message_ids"] == []


def test_tx_trans_001_cache_only_completion_is_committed(security_api):
    client, _, factory = security_api
    ids = _seed_memory(factory, same_account=True)
    response = client.post(
        f"/api/v1/conversations/{ids['allowed_conversation']}/translations",
        headers={"x-session-token": _login(client)},
        json={"anchor_message_id": ids["allowed_message"], "window_size": 1},
    )
    assert response.status_code == 202
    assert response.json()["status"] == "completed"
    with factory() as session:
        row = session.scalar(
            select(MessageTranslation).where(
                MessageTranslation.message_id == ids["allowed_message"]
            )
        )
        assert row is not None
        assert row.translated_text == "正确译文"


def test_tx_trans_001_reuse_updates_failed_row_instead_of_duplicate(security_api):
    client, _, factory = security_api
    ids = _seed_memory(factory, same_account=True, existing_failed=True)
    response = client.post(
        f"/api/v1/conversations/{ids['allowed_conversation']}/translations",
        headers={"x-session-token": _login(client)},
        json={"anchor_message_id": ids["allowed_message"], "window_size": 1},
    )
    assert response.status_code == 202
    with factory() as session:
        rows = session.scalars(
            select(MessageTranslation).where(
                MessageTranslation.message_id == ids["allowed_message"]
            )
        ).all()
        assert len(rows) == 1
        assert rows[0].status == "completed"
        assert rows[0].error_code is None


def test_fr_ai_014_inbound_hash_preserves_exact_source():
    assert source_text_hash("hello ") == hashlib.sha256(b"hello ").hexdigest()
    assert source_text_hash("hello ") != source_text_hash("hello")


def test_fr_ai_014_old_completed_version_does_not_suppress_inbound(security_api):
    _, _, factory = security_api
    ids = _seed_memory(factory, same_account=True)
    with factory() as session:
        message = session.get(Message, ids["allowed_message"])
        session.add(
            MessageTranslation(
                account_id=message.account_id,
                conversation_id=message.conversation_id,
                message_id=message.id,
                target_lang="zh-CN",
                source_text_hash=hashlib.sha256(b"old").hexdigest(),
                status="completed",
                translated_text="旧版本",
            )
        )
        session.commit()
        message.content = "Completely new version"
        session.flush()
        result = enqueue_for_inbound_translation(
            session,
            session.get(WhatsAppAccount, message.account_id),
            session.get(Conversation, message.conversation_id),
            message,
        )
        assert result is not None
