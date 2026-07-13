"""FR-PLG-007/008 + FR-AI-012：受控人设 V1 API 契约。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from whatsapp_chat_system.db.base import Base
from whatsapp_chat_system.db import models as _models  # noqa: F401
from whatsapp_chat_system.standalone_api import (
    _current_alembic_head,
    build_standalone_app,
)

PASSWORD = "standalone-test-password"
EXPECTED_IDS = {"tong-jincheng", "professional-service", "mature-uncle"}


def _bootstrap_app(tmp_path: Path, *, migrated: bool = True):
    database = tmp_path / "business.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{database}"
    os.environ["WHATSAPP_BRIDGE_INTERNAL_TOKEN"] = "test-internal-token"
    os.environ["CHAT_SYSTEM_BOOTSTRAP_PASSWORD"] = PASSWORD

    if migrated:
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
        engine.dispose()
    app = build_standalone_app(runtime_dir=tmp_path / "runtime")
    return app, tmp_path / "runtime"


def _login(client: TestClient) -> str:
    response = client.post("/api/login", json={"password": PASSWORD})
    assert response.status_code == 200
    return response.json()["session_token"]


@pytest.fixture()
def migrated_client(tmp_path: Path):
    app, runtime_dir = _bootstrap_app(tmp_path, migrated=True)
    with TestClient(app) as client:
        yield client, runtime_dir


def test_get_personas_requires_authentication(tmp_path: Path):
    app, _ = _bootstrap_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/api/v1/personas")
    assert response.status_code == 401


def test_get_personas_returns_known_personas_and_default_state(migrated_client):
    client, _ = migrated_client
    token = _login(client)
    response = client.get("/api/v1/personas", headers={"x-session-token": token})
    assert response.status_code == 200
    payload = response.json()
    assert {item["id"] for item in payload["items"]} == EXPECTED_IDS
    assert (
        next(item for item in payload["items"] if item["id"] == "tong-jincheng")["name"]
        == "童锦程·直球关系顾问"
    )
    assert payload["plugin_enabled"] is True
    assert payload["contact_assignments"] == {}
    for item in payload["items"]:
        assert item["available"] is True
        assert set(item.keys()) == {
            "id",
            "name",
            "description",
            "category",
            "accent",
            "available",
        }
        assert "prompt" not in item


def test_enable_persona_persists_and_round_trips(migrated_client):
    client, _ = migrated_client
    token = _login(client)
    response = client.put(
        "/api/v1/personas/tong-jincheng/enable",
        json={"enabled": False},
        headers={"x-session-token": token},
    )
    assert response.status_code == 200
    assert response.json() == {"id": "tong-jincheng", "enabled": False}
    list_response = client.get("/api/v1/personas", headers={"x-session-token": token})
    assert list_response.json()["plugin_enabled"] is False

    restore = client.put(
        "/api/v1/personas/professional-service/enable",
        json={"enabled": True},
        headers={"x-session-token": token},
    )
    assert restore.status_code == 200
    assert restore.json() == {"id": "professional-service", "enabled": True}
    list_response = client.get("/api/v1/personas", headers={"x-session-token": token})
    assert list_response.json()["plugin_enabled"] is True


def test_enable_unknown_persona_returns_404(migrated_client):
    client, _ = migrated_client
    token = _login(client)
    response = client.put(
        "/api/v1/personas/unicorn/enable",
        json={"enabled": True},
        headers={"x-session-token": token},
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "persona_not_found"


def test_enable_default_persona_is_immutable(migrated_client):
    client, _ = migrated_client
    token = _login(client)
    response = client.put(
        "/api/v1/personas/default/enable",
        json={"enabled": False},
        headers={"x-session-token": token},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "persona_default_immutable"


def test_assign_persona_to_contact_round_trips(migrated_client):
    client, _ = migrated_client
    token = _login(client)
    response = client.put(
        "/api/v1/contacts/12345@lid/persona",
        json={"persona_id": "mature-uncle"},
        headers={"x-session-token": token},
    )
    assert response.status_code == 200
    assert response.json() == {"contact_id": "12345@lid", "persona_id": "mature-uncle"}
    listed = client.get("/api/v1/personas", headers={"x-session-token": token})
    assert listed.json()["contact_assignments"] == {"12345@lid": "mature-uncle"}


def test_assign_unknown_persona_returns_404(migrated_client):
    client, _ = migrated_client
    token = _login(client)
    response = client.put(
        "/api/v1/contacts/12345@lid/persona",
        json={"persona_id": "fake-id"},
        headers={"x-session-token": token},
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "persona_not_found"


def test_assign_default_clears_assignment(migrated_client):
    client, _ = migrated_client
    token = _login(client)
    client.put(
        "/api/v1/contacts/12345@lid/persona",
        json={"persona_id": "tong-jincheng"},
        headers={"x-session-token": token},
    )
    response = client.put(
        "/api/v1/contacts/12345@lid/persona",
        json={"persona_id": "default"},
        headers={"x-session-token": token},
    )
    assert response.status_code == 200
    assert response.json()["persona_id"] == "default"
    listed = client.get("/api/v1/personas", headers={"x-session-token": token})
    assert "12345@lid" not in listed.json()["contact_assignments"]


def test_repeated_assign_is_idempotent(migrated_client):
    client, _ = migrated_client
    token = _login(client)
    body = {"persona_id": "professional-service"}
    headers = {"x-session-token": token}
    first = client.put(
        "/api/v1/contacts/7777@s.whatsapp.net/persona", json=body, headers=headers
    )
    second = client.put(
        "/api/v1/contacts/7777@s.whatsapp.net/persona", json=body, headers=headers
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
