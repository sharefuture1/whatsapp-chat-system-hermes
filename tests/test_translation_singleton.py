"""PERF-003：翻译端点必须复用 app 级 Rewriter/Provider，不得每请求新建。"""

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

import whatsapp_chat_system.api.v1.messages as messages_module
from whatsapp_chat_system.db import Base, create_session_factory
from whatsapp_chat_system.db.models import (
    Contact,
    Conversation,
    Message,
    WhatsAppAccount,
)
from whatsapp_chat_system.rewriter import RewriteResult
from whatsapp_chat_system.standalone_api import (
    _current_alembic_head,
    build_standalone_app,
)

PASSWORD = "standalone-test-password"


def _id() -> str:
    return str(uuid4())


def _standalone_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    runtime_dir = tmp_path / "runtime"
    database = tmp_path / "business.db"
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database}")
    monkeypatch.setenv("WHATSAPP_BRIDGE_INTERNAL_TOKEN", "test-internal-token")
    monkeypatch.setenv("CHAT_SYSTEM_BOOTSTRAP_PASSWORD", PASSWORD)
    engine = create_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        )
        connection.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
            {"revision": _current_alembic_head()},
        )
    factory = create_session_factory(engine)
    message_ids = []
    with factory() as session:
        account = WhatsAppAccount(
            id=_id(), name="acct", status="online", session_ref="account:test"
        )
        contact = Contact(id=_id(), account_id=account.id, remote_jid="123@lid")
        conversation = Conversation(
            id=_id(), account_id=account.id, contact_id=contact.id, remote_jid="123@lid"
        )
        for wa_id, content in (("wamid-1", "ສະບາຍດີ"), ("wamid-2", "ຂອບໃຈ")):
            message = Message(
                id=_id(),
                account_id=account.id,
                conversation_id=conversation.id,
                contact_id=contact.id,
                wa_message_id=wa_id,
                direction="inbound",
                message_type="text",
                content=content,
                status="received",
                occurred_at=datetime.now(timezone.utc),
            )
            session.add(message)
            message_ids.append(message.id)
        session.add_all([account, contact, conversation])
        session.commit()
    engine.dispose()
    return build_standalone_app(runtime_dir=runtime_dir), message_ids


class _CountingRewriter:
    instances = 0

    def __init__(self, *args, **kwargs):
        type(self).instances += 1

    def translate_to_zh_result(self, text_value, source_lang):
        return RewriteResult(language="Chinese", message=f"译文:{text_value}")


def test_translate_endpoint_reuses_single_rewriter(tmp_path, monkeypatch):
    app, message_ids = _standalone_app(tmp_path, monkeypatch)
    _CountingRewriter.instances = 0
    monkeypatch.setattr(messages_module, "Rewriter", _CountingRewriter)

    with TestClient(app) as client:
        token = client.post(
            "/api/login", json={"username": "admin", "password": PASSWORD}
        ).json()["session_token"]
        headers = {"x-session-token": token}
        for message_id, source in zip(message_ids, ("ສະບາຍດີ", "ຂອບໃຈ")):
            response = client.post(
                f"/api/v1/messages/{message_id}/translate",
                json={"content": source},
                headers=headers,
            )
            assert response.status_code == 200
            assert response.json()["translated"] == f"译文:{source}"

    assert _CountingRewriter.instances == 1, "两次翻译必须复用同一个 Rewriter 实例"
