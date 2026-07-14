from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


DEFAULT_DATABASE_URL = "sqlite:///./data/whatsapp-chat-system.db"


def test_database_settings_default_sqlite_url_does_not_require_hermes(
    monkeypatch, tmp_path
):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home-without-hermes"))

    from whatsapp_chat_system.settings import DatabaseSettings

    assert DatabaseSettings.from_env().database_url == DEFAULT_DATABASE_URL


def test_database_settings_database_url_override():
    from whatsapp_chat_system.settings import DatabaseSettings

    settings = DatabaseSettings.from_env(
        {"DATABASE_URL": "postgresql+psycopg://db/app"}
    )

    assert settings.database_url == "postgresql+psycopg://db/app"


def test_sqlite_engine_enables_foreign_keys():
    from whatsapp_chat_system.db.session import create_engine, create_session_factory
    from whatsapp_chat_system.settings import DatabaseSettings

    engine = create_engine(DatabaseSettings(database_url="sqlite:///:memory:"))
    session = create_session_factory(engine)()
    try:
        assert session.get_bind() is engine
        with engine.connect() as connection:
            enabled = connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one()
    finally:
        session.close()
        engine.dispose()

    assert enabled == 1


class RecordingSession:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def commit(self) -> None:
        self.calls.append("commit")

    def rollback(self) -> None:
        self.calls.append("rollback")

    def close(self) -> None:
        self.calls.append("close")


def test_session_scope_commits_and_always_closes():
    from whatsapp_chat_system.db.session import session_scope

    session = RecordingSession()

    with session_scope(lambda: session) as yielded:
        assert yielded is session

    assert session.calls == ["commit", "close"]


def test_session_scope_rolls_back_reraises_and_always_closes():
    from whatsapp_chat_system.db.session import session_scope

    session = RecordingSession()

    with pytest.raises(RuntimeError, match="boom"):
        with session_scope(lambda: session):
            raise RuntimeError("boom")

    assert session.calls == ["rollback", "close"]


def test_importing_application_and_db_modules_does_not_create_database(tmp_path):
    database_path = tmp_path / "must-not-exist.db"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{database_path}"

    subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import whatsapp_chat_system; "
                "import whatsapp_chat_system.db; "
                "import whatsapp_chat_system.web_api"
            ),
        ],
        check=True,
        env=env,
    )

    assert not database_path.exists()
    assert not list(Path(tmp_path).glob("*.db"))


def test_engine_kwargs_enable_pool_health_for_server_databases():
    from whatsapp_chat_system.db.session import _engine_kwargs

    kwargs = _engine_kwargs("postgresql+psycopg://db/app")

    assert kwargs["pool_pre_ping"] is True
    assert kwargs["pool_recycle"] == 1800
    assert kwargs["pool_size"] >= 5
    assert kwargs["max_overflow"] >= 5


def test_engine_kwargs_keep_sqlite_defaults():
    from whatsapp_chat_system.db.session import _engine_kwargs

    assert _engine_kwargs("sqlite:///:memory:") == {}
    assert _engine_kwargs("sqlite:///./data/app.db") == {}


def test_sqlite_engine_still_created_with_pooled_factory():
    from whatsapp_chat_system.db.session import create_engine
    from whatsapp_chat_system.settings import DatabaseSettings

    engine = create_engine(DatabaseSettings(database_url="sqlite:///:memory:"))
    try:
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT 1").scalar_one() == 1
    finally:
        engine.dispose()
