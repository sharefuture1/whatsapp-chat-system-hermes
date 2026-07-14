from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from whatsapp_chat_system.db import Base
from whatsapp_chat_system.db import models as _models  # noqa: F401
from whatsapp_chat_system.standalone_api import _current_alembic_head, build_standalone_app

PASSWORD = "plugin-test-password"


def app(tmp_path: Path):
    database = tmp_path / "business.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{database}"
    os.environ["WHATSAPP_BRIDGE_INTERNAL_TOKEN"] = "plugin-test-token"
    os.environ["CHAT_SYSTEM_BOOTSTRAP_PASSWORD"] = PASSWORD
    engine = create_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        connection.execute(text("INSERT INTO alembic_version (version_num) VALUES (:revision)"), {"revision": _current_alembic_head()})
    engine.dispose()
    return build_standalone_app(runtime_dir=tmp_path / "runtime")


def login(client: TestClient) -> str:
    response = client.post("/api/login", json={"password": PASSWORD})
    assert response.status_code == 200
    return response.json()["session_token"]


def test_plugin_catalog_exposes_real_capabilities(tmp_path: Path):
    with TestClient(app(tmp_path)) as client:
        token = login(client)
        response = client.get("/api/v1/plugins", headers={"x-session-token": token})
        assert response.status_code == 200
        items = {item["id"]: item for item in response.json()["items"]}
        assert items["auto_translate"]["available"] is True
        assert items["persona_styles"]["available"] is True
        assert items["schedule"]["available"] is False
        assert items["broadcast"]["available"] is False
        assert items["schedule"]["enabled"] is False
        assert items["schedule"]["unavailable_reason"]
        assert items["schedule"]["hooks"]


def test_unavailable_plugin_cannot_be_enabled(tmp_path: Path):
    with TestClient(app(tmp_path)) as client:
        token = login(client)
        response = client.post(
            "/api/v1/plugins/toggle",
            json={"plugin_id": "schedule", "enabled": True},
            headers={"x-session-token": token},
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "plugin_unavailable"


def test_available_plugin_toggle_persists(tmp_path: Path):
    with TestClient(app(tmp_path)) as client:
        token = login(client)
        headers = {"x-session-token": token}
        response = client.post("/api/v1/plugins/toggle", json={"plugin_id": "auto_translate", "enabled": False}, headers=headers)
        assert response.status_code == 200
        assert response.json()["enabled"] is False
        items = client.get("/api/v1/plugins", headers=headers).json()["items"]
        assert next(item for item in items if item["id"] == "auto_translate")["enabled"] is False
