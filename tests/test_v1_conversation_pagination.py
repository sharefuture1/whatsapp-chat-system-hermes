from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from whatsapp_chat_system.api.v1.conversations import create_conversations_router
from whatsapp_chat_system.db import Base
from whatsapp_chat_system.db.models import (
    Contact,
    Conversation,
    Message,
    WhatsAppAccount,
)


def build_client() -> tuple[TestClient, str]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        account = WhatsAppAccount(name="WA1", session_ref="session-wa1")
        session.add(account)
        session.flush()
        contact = Contact(account_id=account.id, remote_jid="100@s.whatsapp.net")
        session.add(contact)
        session.flush()
        conversation = Conversation(
            account_id=account.id,
            contact_id=contact.id,
            remote_jid=contact.remote_jid,
            title="Test",
        )
        session.add(conversation)
        session.flush()
        base = datetime(2026, 7, 13, 10, 0, tzinfo=timezone.utc)
        for index in range(5):
            session.add(
                Message(
                    account_id=account.id,
                    conversation_id=conversation.id,
                    contact_id=contact.id,
                    direction="inbound",
                    content=f"message-{index}",
                    status="received",
                    occurred_at=base + timedelta(minutes=index),
                )
            )
        session.commit()
        conversation_id = conversation.id

    app = FastAPI()
    app.state.runtime = SimpleNamespace(
        web_settings={
            "sessions": {
                "pagination-test-token": {
                    "username": "pagination-reader",
                    "expires_at": 9_999_999_999,
                }
            },
            "users": {
                "pagination-reader": {
                    "role": "viewer",
                    "allowed_account_ids": [account.id],
                }
            },
        }
    )
    app.include_router(create_conversations_router(factory))
    client = TestClient(app)
    client.headers.update({"x-session-token": "pagination-test-token"})
    return client, conversation_id


def test_cursor_paginates_without_overlap() -> None:
    client, conversation_id = build_client()

    first_response = client.get(
        f"/api/v1/conversations/{conversation_id}/messages",
        params={"limit": 2},
    )
    assert first_response.status_code == 200
    first = first_response.json()
    assert [item["content"] for item in first["messages"]] == [
        "message-3",
        "message-4",
    ]
    assert first["total_messages"] == 5
    assert first["has_more"] is True
    assert first["next_cursor"]

    second_response = client.get(
        f"/api/v1/conversations/{conversation_id}/messages",
        params={"limit": 2, **first["next_cursor"]},
    )
    assert second_response.status_code == 200
    second = second_response.json()
    assert [item["content"] for item in second["messages"]] == [
        "message-1",
        "message-2",
    ]
    assert second["total_messages"] == 5
    assert second["has_more"] is True

    third_response = client.get(
        f"/api/v1/conversations/{conversation_id}/messages",
        params={"limit": 2, **second["next_cursor"]},
    )
    assert third_response.status_code == 200
    third = third_response.json()
    assert [item["content"] for item in third["messages"]] == ["message-0"]
    assert third["total_messages"] == 5
    assert third["has_more"] is False
    assert third["next_cursor"] is None


def test_cursor_rejects_id_without_timestamp() -> None:
    client, conversation_id = build_client()
    response = client.get(
        f"/api/v1/conversations/{conversation_id}/messages",
        params={"before_id": "message-id-only"},
    )
    assert response.status_code == 422
