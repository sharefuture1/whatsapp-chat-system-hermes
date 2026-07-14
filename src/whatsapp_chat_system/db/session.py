from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import TypeVar

from sqlalchemy import Engine, create_engine as sqlalchemy_create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from whatsapp_chat_system.settings import DatabaseSettings


SessionT = TypeVar("SessionT")


def _engine_kwargs(database_url: str) -> dict[str, object]:
    """服务器型数据库（PostgreSQL 等）启用连接池健康配置；SQLite 保持默认。"""

    if database_url.startswith("sqlite"):
        return {}
    return {
        "pool_pre_ping": True,
        "pool_recycle": 1800,
        "pool_size": 10,
        "max_overflow": 20,
    }


def create_engine(settings: DatabaseSettings | None = None) -> Engine:
    """创建业务数据库 Engine；SQLite 连接自动启用外键约束。"""

    resolved_settings = settings or DatabaseSettings.from_env()
    engine = sqlalchemy_create_engine(
        resolved_settings.database_url,
        **_engine_kwargs(resolved_settings.database_url),
    )
    if engine.dialect.name == "sqlite":
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


def _enable_sqlite_foreign_keys(
    dbapi_connection: object, _connection_record: object
) -> None:
    cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """创建显式绑定到 Engine 的 SQLAlchemy 2 Session factory。"""

    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False)


@contextmanager
def session_scope(session_factory: Callable[[], SessionT]) -> Iterator[SessionT]:
    """提供 commit/rollback/close 完整生命周期的事务边界。"""

    session = session_factory()
    try:
        yield session
        session.commit()  # type: ignore[attr-defined]
    except Exception:
        session.rollback()  # type: ignore[attr-defined]
        raise
    finally:
        session.close()  # type: ignore[attr-defined]
