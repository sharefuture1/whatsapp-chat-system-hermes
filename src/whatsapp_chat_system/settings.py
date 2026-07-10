from __future__ import annotations

from dataclasses import dataclass
from os import environ
from typing import Mapping
from urllib.parse import urlsplit, urlunsplit


DEFAULT_WENDING_AI_BASE_URL = 'https://wendingai.future1.us/v1'
DEFAULT_WENDING_AI_MODEL = 'gpt-5.3-codex-spark'
DEFAULT_WENDING_AI_TIMEOUT_SECONDS = 90
DEFAULT_WENDING_AI_MAX_RETRIES = 2
MAX_WENDING_AI_TIMEOUT_SECONDS = 300
MAX_WENDING_AI_RETRIES = 5
DEFAULT_DATABASE_URL = 'sqlite:///./data/whatsapp-chat-system.db'


@dataclass(frozen=True, slots=True)
class DatabaseSettings:
    """独立业务数据库配置，不读取 Hermes profile 或 config。"""

    database_url: str = DEFAULT_DATABASE_URL

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> 'DatabaseSettings':
        values = environ if env is None else env
        database_url = (values.get('DATABASE_URL') or '').strip() or DEFAULT_DATABASE_URL
        return cls(database_url=database_url)


@dataclass(frozen=True, slots=True)
class AISettings:
    """独立于 Hermes profile 的问鼎 AI 运行配置。"""

    base_url: str = DEFAULT_WENDING_AI_BASE_URL
    api_key: str = ''
    default_model: str = DEFAULT_WENDING_AI_MODEL
    timeout_seconds: int = DEFAULT_WENDING_AI_TIMEOUT_SECONDS
    max_retries: int = DEFAULT_WENDING_AI_MAX_RETRIES

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> 'AISettings':
        values = environ if env is None else env
        default_model = (values.get('WENDING_AI_DEFAULT_MODEL') or '').strip() or DEFAULT_WENDING_AI_MODEL
        return cls(
            base_url=_normalize_base_url(values.get('WENDING_AI_BASE_URL')),
            api_key=(values.get('WENDING_AI_API_KEY') or '').strip(),
            default_model=default_model,
            timeout_seconds=_bounded_int(
                values.get('WENDING_AI_TIMEOUT_SECONDS'),
                DEFAULT_WENDING_AI_TIMEOUT_SECONDS,
                minimum=1,
                maximum=MAX_WENDING_AI_TIMEOUT_SECONDS,
            ),
            max_retries=_bounded_int(
                values.get('WENDING_AI_MAX_RETRIES'),
                DEFAULT_WENDING_AI_MAX_RETRIES,
                minimum=0,
                maximum=MAX_WENDING_AI_RETRIES,
            ),
        )

    def safe_dict(self) -> dict[str, object]:
        return {
            'provider': 'wendingai',
            'base_url': _normalize_base_url(self.base_url),
            'default_model': self.default_model.strip() or DEFAULT_WENDING_AI_MODEL,
            'timeout_seconds': self.timeout_seconds,
            'max_retries': self.max_retries,
            'api_key_configured': bool(self.api_key.strip()),
        }


def _bounded_int(raw: str | None, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default
    return value if minimum <= value <= maximum else default


def _normalize_base_url(raw: str | None) -> str:
    value = (raw or DEFAULT_WENDING_AI_BASE_URL).strip()
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        return DEFAULT_WENDING_AI_BASE_URL
    if parts.scheme not in {'http', 'https'} or not parts.hostname:
        return DEFAULT_WENDING_AI_BASE_URL
    host = parts.hostname
    if ':' in host and not host.startswith('['):
        host = f'[{host}]'
    port_suffix = f':{port}' if port else ''
    path = '/' + parts.path.strip('/') if parts.path.strip('/') else ''
    return urlunsplit((parts.scheme, f'{host}{port_suffix}', path, '', '')).rstrip('/')
