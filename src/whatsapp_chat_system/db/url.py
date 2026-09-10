"""DATABASE_URL 归一化与不安全日志输出的防护。

部署到服务器时用户常写成 `postgres://` 或 `postgresql://`，
而这两种写法在 SQLAlchemy 下会去加载 psycopg2；本项目提供的是 psycopg 3，
因此统一归一成 `postgresql+psycopg://`。
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

#: 未显式指定驱动时，PostgreSQL 使用的驱动
POSTGRES_DRIVER = "psycopg"

_ALIASES = (
    ("postgres://", f"postgresql+{POSTGRES_DRIVER}://"),
    ("postgresql://", f"postgresql+{POSTGRES_DRIVER}://"),
    # psycopg2 不是本项目的依赖，显式写法也归一到 psycopg 3
    ("postgresql+psycopg2://", f"postgresql+{POSTGRES_DRIVER}://"),
)


def normalize_database_url(url: str | None) -> str:
    """把 DATABASE_URL 归一到 SQLAlchemy 可直接使用的形式。"""

    cleaned = (url or "").strip()
    if not cleaned:
        return ""
    lowered = cleaned.lower()
    for prefix, replacement in _ALIASES:
        if lowered.startswith(prefix):
            if prefix == replacement:
                return cleaned
            return replacement + cleaned[len(prefix) :]
    return cleaned


def database_backend(url: str | None) -> str:
    """返回后端类型：``sqlite`` / ``postgresql`` / 其它 dialect 名。"""

    cleaned = normalize_database_url(url)
    if not cleaned:
        return "unknown"
    scheme = cleaned.split("://", 1)[0]
    # 去掉 + 驱动后缀，例如 postgresql+psycopg -> postgresql
    return scheme.split("+", 1)[0]


def is_sqlite(url: str | None) -> bool:
    return database_backend(url) == "sqlite"


def is_postgresql(url: str | None) -> bool:
    return database_backend(url) == "postgresql"


def sqlite_file_path(url: str | None) -> str | None:
    """取出 SQLite 文件路径；内存库或非 SQLite 返回 None。"""

    cleaned = normalize_database_url(url)
    if not is_sqlite(cleaned):
        return None
    # sqlite:///relative.db -> relative.db ；sqlite:////abs.db -> /abs.db
    _, _, path = cleaned.partition("sqlite:///")
    if not path or path == ":memory:":
        return None
    return path


def describe_database_url(url: str | None) -> str:
    """脱敏后适合写入日志/健康检查的连接描述。"""

    cleaned = normalize_database_url(url)
    if not cleaned:
        return "(unset)"
    if is_sqlite(cleaned):
        return cleaned
    try:
        parts = urlsplit(cleaned)
    except ValueError:
        return "(invalid database url)"
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    user = parts.username or ""
    credentials = f"{user}:***@" if user else ""
    database = parts.path.lstrip("/")
    return urlunsplit(
        (parts.scheme, f"{credentials}{host}", f"/{database}", "", "")
    )
