"""Standalone runtime regression tests (SEC / MIG readiness contracts)."""

from __future__ import annotations

import inspect
import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from whatsapp_chat_system.cli import build_parser
from whatsapp_chat_system.db.base import Base
from whatsapp_chat_system.db import models as _models  # noqa: F401
from whatsapp_chat_system.runtime import StandaloneRuntime
from whatsapp_chat_system.standalone_api import (
    _current_alembic_head,
    build_standalone_app,
)

PASSWORD = "standalone-test-password"


def standalone_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, migrated: bool = True
):
    runtime_dir = tmp_path / "runtime"
    database = tmp_path / "business.db"
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database}")
    monkeypatch.setenv("WHATSAPP_BRIDGE_INTERNAL_TOKEN", "test-internal-token")
    monkeypatch.setenv("CHAT_SYSTEM_BOOTSTRAP_PASSWORD", PASSWORD)
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
    return build_standalone_app(runtime_dir=runtime_dir), runtime_dir


def test_standalone_build_does_not_import_legacy_web_api_and_health_is_safe(
    tmp_path, monkeypatch
):
    sentinel = tmp_path / "hermes-sentinel"
    monkeypatch.setenv("HERMES_HOME", str(sentinel))
    app, runtime_dir = standalone_app(tmp_path, monkeypatch)

    assert "web_api" not in inspect.getsource(build_standalone_app)
    with TestClient(app) as client:
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["runtime_mode"] == "standalone"
        assert "profile" not in response.json()
        assert client.get("/api/v1/accounts").status_code == 401
    assert not sentinel.exists()
    assert runtime_dir.is_dir()


@pytest.mark.parametrize(
    "path", ["/api", "/api/dashboard", "/api/conversations", "/api/anything/legacy"]
)
def test_legacy_apis_are_410_before_auth_for_anonymous_and_authenticated(
    tmp_path, monkeypatch, path
):
    app, _ = standalone_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        anonymous = client.get(path)
        assert anonymous.status_code == 410
        assert anonymous.json() == {"code": "legacy_api_disabled"}
        assert anonymous.headers["X-Request-ID"]
        token = client.post("/api/login", json={"password": PASSWORD}).json()[
            "session_token"
        ]
        authenticated = client.get(path, headers={"x-session-token": token})
        assert authenticated.status_code == 410
        unauthorized_v1 = client.get("/api/v1/accounts")
        assert unauthorized_v1.status_code == 401
        assert unauthorized_v1.headers["X-Request-ID"]


def test_empty_database_refuses_startup(tmp_path, monkeypatch):
    app, _ = standalone_app(tmp_path, monkeypatch, migrated=False)
    with pytest.raises(RuntimeError, match="schema is not ready"):
        with TestClient(app):
            pass


def test_create_all_database_without_alembic_revision_refuses_startup(
    tmp_path, monkeypatch
):
    app, _ = standalone_app(tmp_path, monkeypatch, migrated=False)
    database = tmp_path / "business.db"
    engine = create_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine)
    engine.dispose()

    with pytest.raises(RuntimeError, match="schema is not ready"):
        with TestClient(app):
            pass


def test_database_with_wrong_alembic_revision_refuses_startup(tmp_path, monkeypatch):
    app, _ = standalone_app(tmp_path, monkeypatch, migrated=False)
    database = tmp_path / "business.db"
    engine = create_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        )
        connection.execute(
            text("INSERT INTO alembic_version (version_num) VALUES ('not-the-head')")
        )
    engine.dispose()

    with pytest.raises(RuntimeError, match="schema is not ready"):
        with TestClient(app):
            pass


@pytest.mark.parametrize("missing_or_weak", [None, "short"])
def test_standalone_bootstrap_password_is_required_and_strong(
    tmp_path, monkeypatch, missing_or_weak
):
    monkeypatch.setenv("CHAT_SYSTEM_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'business.db'}")
    monkeypatch.setenv("WHATSAPP_BRIDGE_INTERNAL_TOKEN", "test-internal-token")
    if missing_or_weak is None:
        monkeypatch.delenv("CHAT_SYSTEM_BOOTSTRAP_PASSWORD", raising=False)
    else:
        monkeypatch.setenv("CHAT_SYSTEM_BOOTSTRAP_PASSWORD", missing_or_weak)
    with pytest.raises(RuntimeError, match="BOOTSTRAP_PASSWORD"):
        build_standalone_app()


def test_bootstrap_password_is_only_required_on_first_initialization(
    tmp_path, monkeypatch
):
    app, runtime_dir = standalone_app(tmp_path, monkeypatch)
    assert (runtime_dir / "web-settings.json").is_file()

    monkeypatch.delenv("CHAT_SYSTEM_BOOTSTRAP_PASSWORD", raising=False)
    restarted = build_standalone_app(runtime_dir=runtime_dir)
    with TestClient(restarted) as client:
        login = client.post("/api/login", json={"password": PASSWORD})
    assert login.status_code == 200
    assert login.json()["success"] is True


def test_existing_invalid_auth_settings_fail_closed_without_bootstrap_password(
    tmp_path, monkeypatch
):
    app, runtime_dir = standalone_app(tmp_path, monkeypatch)
    assert app is not None
    (runtime_dir / "web-settings.json").write_text('{"auth": {}}', encoding="utf-8")
    monkeypatch.delenv("CHAT_SYSTEM_BOOTSTRAP_PASSWORD", raising=False)
    with pytest.raises(RuntimeError, match="authentication settings"):
        build_standalone_app(runtime_dir=runtime_dir)


def test_internal_event_validation_errors_are_structured_and_authenticated_first(
    tmp_path, monkeypatch
):
    app, _ = standalone_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        malformed = client.post(
            "/internal/events/whatsapp",
            json={},
            headers={
                "X-Internal-Token": "test-internal-token",
            },
        )
        assert malformed.status_code == 422
        assert malformed.json()["error"]["code"] == "validation_error"
        assert malformed.headers["X-Request-ID"]

        anonymous_malformed = client.post("/internal/events/whatsapp", json={})
        assert anonymous_malformed.status_code == 401
        assert anonymous_malformed.headers["X-Request-ID"]


@pytest.mark.parametrize("missing", ["DATABASE_URL", "WHATSAPP_BRIDGE_INTERNAL_TOKEN"])
def test_standalone_build_fails_closed_when_required_environment_is_missing(
    tmp_path, monkeypatch, missing
):
    monkeypatch.setenv("CHAT_SYSTEM_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'business.db'}")
    monkeypatch.setenv("WHATSAPP_BRIDGE_INTERNAL_TOKEN", "test-internal-token")
    monkeypatch.setenv("CHAT_SYSTEM_BOOTSTRAP_PASSWORD", PASSWORD)
    monkeypatch.delenv(missing, raising=False)
    with pytest.raises(RuntimeError, match="standalone runtime configuration"):
        build_standalone_app()


def test_runtime_settings_are_private_atomic_and_corrupt_json_fails_closed(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'business.db'}")
    monkeypatch.setenv("WHATSAPP_BRIDGE_INTERNAL_TOKEN", "test-internal-token")
    monkeypatch.setenv("CHAT_SYSTEM_BOOTSTRAP_PASSWORD", PASSWORD)
    runtime = StandaloneRuntime.from_env(tmp_path / "runtime")
    assert stat.S_IMODE(runtime.paths.root.stat().st_mode) == 0o700
    assert stat.S_IMODE(runtime.paths.web_settings_file.stat().st_mode) == 0o600
    runtime.paths.web_settings_file.write_text("{not JSON", encoding="utf-8")
    with pytest.raises(RuntimeError, match="invalid standalone runtime settings JSON"):
        StandaloneRuntime.from_env(tmp_path / "runtime")


def test_serve_parser_has_no_profile_argument():
    parser = build_parser()
    serve = next(
        action
        for action in parser._actions
        if getattr(action, "dest", None) == "command"
    )
    serve_parser = serve.choices["serve"]
    assert all(action.dest != "profile" for action in parser._actions)
    assert all(action.dest != "profile" for action in serve_parser._actions)
