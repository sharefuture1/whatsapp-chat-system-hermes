"""DATABASE_URL 归一化：让同一份配置在 SQLite 与 PostgreSQL 上都能直接用。

部署到服务器时最常见的坑是把 URL 写成 `postgres://` —— 那会让 SQLAlchemy
去加载 psycopg2，而本项目提供的是 psycopg 3，于是启动即失败。
"""

from __future__ import annotations

import pytest

from whatsapp_chat_system.db.url import (
    database_backend,
    describe_database_url,
    is_postgresql,
    is_sqlite,
    normalize_database_url,
    sqlite_file_path,
)
from whatsapp_chat_system.settings import DatabaseSettings


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # 常见简写统一走 psycopg 3
        ("postgres://u:p@db:5432/app", "postgresql+psycopg://u:p@db:5432/app"),
        ("postgresql://u:p@db:5432/app", "postgresql+psycopg://u:p@db:5432/app"),
        # 显式写了 psycopg2 也归一，因为该驱动不是本项目的依赖
        (
            "postgresql+psycopg2://u:p@db/app",
            "postgresql+psycopg://u:p@db/app",
        ),
        # 已经是正确写法则原样保留
        (
            "postgresql+psycopg://u:p@db/app",
            "postgresql+psycopg://u:p@db/app",
        ),
        # SQLite 不受影响
        ("sqlite:///./data/app.db", "sqlite:///./data/app.db"),
        ("sqlite:///:memory:", "sqlite:///:memory:"),
    ],
)
def test_normalize_database_url(raw, expected):
    assert normalize_database_url(raw) == expected


def test_normalize_is_idempotent():
    once = normalize_database_url("postgres://u:p@db/app")
    assert normalize_database_url(once) == once


def test_normalize_handles_blank_and_none():
    assert normalize_database_url("") == ""
    assert normalize_database_url(None) == ""
    assert normalize_database_url("   ") == ""


def test_normalize_preserves_query_parameters():
    raw = "postgres://u:p@db/app?sslmode=require&connect_timeout=5"
    assert normalize_database_url(raw) == (
        "postgresql+psycopg://u:p@db/app?sslmode=require&connect_timeout=5"
    )


def test_normalize_is_case_insensitive_on_scheme():
    assert normalize_database_url("POSTGRES://u@db/app") == (
        "postgresql+psycopg://u@db/app"
    )


@pytest.mark.parametrize(
    ("url", "backend"),
    [
        ("postgres://u@db/app", "postgresql"),
        ("postgresql+psycopg://u@db/app", "postgresql"),
        ("sqlite:///app.db", "sqlite"),
        ("", "unknown"),
    ],
)
def test_database_backend(url, backend):
    assert database_backend(url) == backend


def test_backend_helpers():
    assert is_postgresql("postgresql://u@db/app") is True
    assert is_postgresql("sqlite:///app.db") is False
    assert is_sqlite("sqlite:///app.db") is True
    assert is_sqlite("postgres://u@db/app") is False


@pytest.mark.parametrize(
    ("url", "path"),
    [
        ("sqlite:///./data/app.db", "./data/app.db"),
        ("sqlite:////var/lib/app/app.db", "/var/lib/app/app.db"),
        ("sqlite:///:memory:", None),
        ("postgres://u@db/app", None),
    ],
)
def test_sqlite_file_path(url, path):
    assert sqlite_file_path(url) == path


def test_describe_database_url_masks_password():
    described = describe_database_url("postgres://alice:s3cret@db.internal:5432/app")

    assert "s3cret" not in described
    assert "alice" in described
    assert "db.internal:5432" in described
    assert described.endswith("/app")


def test_describe_database_url_keeps_sqlite_verbatim():
    assert describe_database_url("sqlite:///./data/app.db") == "sqlite:///./data/app.db"


def test_describe_database_url_handles_unset():
    assert describe_database_url("") == "(unset)"
    assert describe_database_url(None) == "(unset)"


def test_database_settings_from_env_normalizes(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@db:5432/app")

    settings = DatabaseSettings.from_env()

    assert settings.database_url == "postgresql+psycopg://u:p@db:5432/app"


def test_database_settings_from_env_uses_default_when_unset(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    settings = DatabaseSettings.from_env()

    assert settings.database_url.startswith("sqlite:///")


def test_create_engine_accepts_bare_postgres_scheme(monkeypatch):
    """回归：`postgres://` 必须能被正确解析到已安装的 psycopg 驱动。"""

    from whatsapp_chat_system.db import create_engine

    settings = DatabaseSettings(database_url="postgres://u:p@127.0.0.1:5432/app")
    engine = create_engine(settings)
    try:
        assert engine.dialect.name == "postgresql"
        assert engine.dialect.driver == "psycopg"
    finally:
        engine.dispose()


def test_create_engine_rejects_empty_url():
    from whatsapp_chat_system.db import create_engine

    with pytest.raises(ValueError):
        create_engine(DatabaseSettings(database_url=""))
