from __future__ import annotations

import secrets
import time
import re
import os
import logging
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .ai.crypto import decrypt_api_key, encrypt_api_key, mask_api_key
from .ai.provider import WendingAIProvider
from .api.v1.accounts import BridgeProtocol, create_accounts_router
from .api.v1.conversations import create_conversations_router
from .api.internal.whatsapp_events import (
    create_whatsapp_events_router,
    whatsapp_validation_exception_handler,
)
from .bridge.client import BridgeClient, BridgeError
from .config import AppConfig, build_password_record, load_json, save_json, verify_password
from .db import create_engine, create_session_factory, session_scope
from .db.models import AIRuntimeSetting
from .forwarder import AdminForwarder
from .settings import AISettings
from .memory_refresh import MemoryRefresher
from .origins import OriginsCache
from .router import AdminRouter
from .storage import StateDB
from .structured_profile import read_sidecar
from .translations import bulk_put, load_many, load_translations, put_translation
from .rewriter import Rewriter as _Rewriter  # imported for translation helper below


logger = logging.getLogger(__name__)


class ChannelConfig(BaseModel):
    id: str
    name: str
    platform: str
    target: str
    enabled: bool = True
    kinds: list[str] = Field(default_factory=list)


class ReplyRequest(BaseModel):
    target: str
    message: str
    use_memory: bool = True
    mode: str = 'direct'
    preview_only: bool = False


class PaginationRequest(BaseModel):
    page: int = 1
    page_size: int = 50


class SearchRequest(BaseModel):
    q: str


class SettingsUpdateRequest(BaseModel):
    channels: list[ChannelConfig]
    web_settings: dict[str, Any] | None = None
    password: str | None = None


class JobRunRequest(BaseModel):
    job: str


class LoginRequest(BaseModel):
    password: str


class WorkspaceCreateRequest(BaseModel):
    id: str | None = None
    label: str
    platform: str
    profile: str | None = None
    profile_path: str | None = None
    enabled: bool = True
    primary: bool = False


class WorkspaceUpdateRequest(BaseModel):
    label: str | None = None
    platform: str | None = None
    profile: str | None = None
    profile_path: str | None = None
    enabled: bool | None = None
    primary: bool | None = None


class ScheduleRequest(BaseModel):
    target: str
    message: str
    run_at: float
    mode: str = 'smart'
    use_memory: bool = True


class BroadcastRequest(BaseModel):
    targets: list[str]
    message: str
    mode: str = 'smart'
    use_memory: bool = True


class PluginToggleRequest(BaseModel):
    plugin_id: str
    enabled: bool


class AISettingsUpdateRequest(BaseModel):
    """AI 设置更新请求；仅传入非空字段以增量更新。"""

    base_url: str | None = Field(default=None, max_length=2048)
    default_model: str | None = Field(default=None, max_length=255)
    api_key: str | None = Field(default=None, max_length=512)  # 空字符串=清除
    timeout_seconds: int | None = Field(default=None, ge=1, le=300)
    max_retries: int | None = Field(default=None, ge=0, le=5)


# ---------------------------------------------------------------------------
# 运行时 AI 设置管理器 — 支持保存后立即热生效，无需重启
# ---------------------------------------------------------------------------

class RuntimeAISettingsManager:
    """线程安全的运行时 AI 配置管理器。

    优先级：DB 加密存储 > 环境变量
    保存后立即更新内存副本，下一次 AI 请求自动使用新配置。
    """

    def __init__(self, base_settings: AISettings) -> None:
        from threading import RLock

        self._lock = RLock()
        self._base = base_settings
        self._override_model: str | None = None
        self._override_base_url: str | None = None
        self._override_api_key: str | None = None
        self._override_timeout: int | None = None
        self._override_retries: int | None = None
        self._db_key_ciphertext: str | None = None
        self._db_key_hint: str | None = None
        self._db_loaded = False

    # -- getters (运行时主读取入口) ----------------------------------------

    @property
    def effective_api_key(self) -> str:
        with self._lock:
            if self._override_api_key is not None:
                return self._override_api_key
            if self._db_key_ciphertext:
                return decrypt_api_key(self._db_key_ciphertext)
            return self._base.api_key

    @property
    def effective_model(self) -> str:
        with self._lock:
            return self._override_model or self._base.default_model

    @property
    def effective_base_url(self) -> str:
        with self._lock:
            return self._override_base_url or self._base.base_url

    @property
    def effective_timeout(self) -> int:
        with self._lock:
            return self._override_timeout or self._base.timeout_seconds

    @property
    def effective_retries(self) -> int:
        with self._lock:
            return self._override_retries or self._base.max_retries

    @property
    def api_key_hint(self) -> str | None:
        with self._lock:
            return self._db_key_hint

    @property
    def has_db_override(self) -> bool:
        with self._lock:
            return self._db_loaded

    # -- DB 加载（启动时调用一次）-----------------------------------------

    def load_from_db(self) -> None:
        """从业务数据库加载 AIRuntimeSetting 行，填充运行时缓存。"""
        engine = create_engine()
        with session_scope(engine) as db:
            row = db.get(AIRuntimeSetting, 'global')
            if row:
                with self._lock:
                    if row.default_model:
                        self._override_model = row.default_model
                    if row.base_url:
                        self._override_base_url = row.base_url
                    self._db_key_ciphertext = row.api_key_ciphertext
                    self._db_key_hint = row.api_key_hint
                    if row.timeout_seconds:
                        self._override_timeout = row.timeout_seconds
                    if row.max_retries:
                        self._override_retries = row.max_retries
                    self._db_loaded = True

    # -- DB 保存（POST 时调用）--------------------------------------------

    def save_to_db(
        self,
        *,
        base_url: str | None = None,
        default_model: str | None = None,
        api_key: str | None = None,
        timeout_seconds: int | None = None,
        max_retries: int | None = None,
    ) -> dict[str, Any]:
        """原子写入/更新 AIRuntimeSetting；返回保存后的公开信息。"""
        from .settings import _normalize_base_url as norm_url

        engine = create_engine()
        with session_scope(engine) as db:
            row = db.get(AIRuntimeSetting, 'global')
            if row is None:
                row = AIRuntimeSetting(id='global', provider='wendingai')
                db.add(row)

            if base_url is not None:
                row.base_url = norm_url(base_url)
                with self._lock:
                    self._override_base_url = row.base_url
            if default_model is not None:
                row.default_model = default_model.strip()
                with self._lock:
                    self._override_model = row.default_model
            if api_key is not None:  # 空字符串=清除，非空=加密存储
                if api_key.strip():
                    ciphertext = encrypt_api_key(api_key.strip())
                    row.api_key_ciphertext = ciphertext
                    row.api_key_hint = mask_api_key(api_key.strip())
                    with self._lock:
                        self._db_key_ciphertext = ciphertext
                        self._db_key_hint = row.api_key_hint
                        self._override_api_key = None  # 清除内存覆盖，改为从 DB 密文解密
                else:
                    row.api_key_ciphertext = None
                    row.api_key_hint = None
                    with self._lock:
                        self._db_key_ciphertext = None
                        self._db_key_hint = None
                        self._override_api_key = None
            if timeout_seconds is not None:
                row.timeout_seconds = timeout_seconds
                with self._lock:
                    self._override_timeout = timeout_seconds
            if max_retries is not None:
                row.max_retries = max_retries
                with self._lock:
                    self._override_retries = max_retries

            db.flush()
            return {
                'base_url': row.base_url,
                'default_model': row.default_model,
                'api_key_hint': row.api_key_hint,
                'api_key_configured': bool(row.api_key_ciphertext),
            }

    def to_safe_dict(self) -> dict[str, Any]:
        """返回安全的公开字典（不含密钥明文）。"""
        return {
            'provider': 'wendingai',
            'base_url': self.effective_base_url,
            'default_model': self.effective_model,
            'timeout_seconds': self.effective_timeout,
            'max_retries': self.effective_retries,
            'api_key_configured': bool(self.effective_api_key),
            'api_key_hint': self.api_key_hint,
        }


# 全局单例（由 setup_ai_runtime_settings 初始化）
_runtime_ai_settings: RuntimeAISettingsManager | None = None


def setup_ai_runtime_settings(base_settings: AISettings) -> RuntimeAISettingsManager:
    global _runtime_ai_settings
    mgr = RuntimeAISettingsManager(base_settings)
    try:
        mgr.load_from_db()
    except Exception:
        pass  # DB 未初始化或迁移未运行；降级到纯 env 模式
    _runtime_ai_settings = mgr
    return mgr


def get_runtime_ai_settings() -> RuntimeAISettingsManager:
    if _runtime_ai_settings is None:
        raise RuntimeError('setup_ai_runtime_settings() must be called before use')
    return _runtime_ai_settings


_origins_cache = OriginsCache(ttl_seconds=30)


def _resolve_frontend_dist(explicit: str | Path | None = None) -> Path | None:
    if explicit:
        candidate = Path(explicit)
        if candidate.is_dir() and (candidate / 'index.html').is_file():
            return candidate
        return None
    candidates: list[Path] = []
    env_value = os.getenv('CHAT_SYSTEM_WEB_DIST', '').strip()
    if env_value:
        candidates.append(Path(env_value))
    repo_dist = Path(__file__).resolve().parents[2] / 'web' / 'dist'
    candidates.extend([
        repo_dist,
        Path('/var/www/whatsapp-chat-system/web/dist'),
    ])
    for candidate in candidates:
        if candidate.is_dir() and (candidate / 'index.html').is_file():
            return candidate
    return None


def _load_origins(config: AppConfig) -> dict[str, dict[str, Any]]:
    return _origins_cache.load(config.paths.sessions_json)


def _load_memory_markdown(config: AppConfig, user_id: str) -> str:
    for path in config.paths.memory_dir.glob(f'*__{user_id}.md'):
        return path.read_text()
    return ''


def _display_user_name(origin: dict[str, Any], user_id: str, session: dict[str, Any]) -> str:
    name = str(origin.get('user_name') or origin.get('chat_name') or user_id)
    source = str(session.get('source') or '')
    if source == 'telegram' and not name.endswith('-tg'):
        return f'{name}-tg'
    return name


def _origin_by_session(config: AppConfig) -> dict[str, dict[str, Any]]:
    origins = _load_origins(config)
    return {
        str(value.get('session_id') or ''): dict(value.get('origin') or {})
        for value in origins.values()
        if isinstance(value, dict) and value.get('session_id')
    }


def _name_for_user(config: AppConfig, user_id: str, session_ids: list[str], fallback: str = '') -> str:
    origins_by_session = _origin_by_session(config)
    for sid in session_ids:
        origin = origins_by_session.get(sid) or {}
        name = str(origin.get('user_name') or origin.get('chat_name') or '').strip()
        if name:
            return name
    return fallback or user_id


def _language_set_for_text(text: str) -> list[str]:
    lang = _language_hint_for(text)
    return [] if lang == 'Unknown' else [lang]


def _hide_messages_enabled(config: AppConfig) -> bool:
    return bool(config.web_settings.get('message_ops', {}).get('hide_messages_enabled', False))


def _hidden_message_ids(config: AppConfig) -> set[int]:
    if not _hide_messages_enabled(config):
        return set()
    return {int(x) for x in (config.web_settings.get('hidden_message_ids') or []) if str(x).isdigit() or isinstance(x, int)}


def _compute_conversation_summaries(config: AppConfig, db: StateDB) -> list[dict[str, Any]]:
    rows = db.fetch_conversation_summaries(config.admin_ids)
    chat_ops = config.web_settings.get('chat_ops') if isinstance(config.web_settings.get('chat_ops'), dict) else {}
    deleted = set(str(x) for x in (chat_ops or {}).get('deleted', []))
    pinned = [str(x) for x in (chat_ops or {}).get('pinned', [])]
    results: list[dict[str, Any]] = []
    for row in rows:
        user_id = str(row['user_id'] or '')
        if not user_id or user_id in deleted:
            continue
        session_ids = [sid for sid in str(row['session_ids'] or '').split(',') if sid]
        user_name = _name_for_user(config, user_id, session_ids, str(row['title'] or ''))
        memory_markdown = _load_memory_markdown(config, user_id)
        sidecar = read_sidecar(user_id, config.paths.memory_dir)
        priority = (sidecar or {}).get('priority') or _infer_priority(memory_markdown)
        last_text = str(row['last_message'] or '')
        results.append({
            'user_id': user_id,
            'user_name': user_name,
            'session_ids': session_ids,
            'platform': str(row['source'] or 'unknown'),
            'workspace_id': str(row['source'] or 'unknown'),
            'last_timestamp': row['last_timestamp'],
            'last_message': last_text,
            'message_count': int(row['message_count'] or 0),
            'user_message_count': int(row['user_message_count'] or 0),
            'assistant_message_count': int(row['assistant_message_count'] or 0),
            'languages': _language_set_for_text(last_text),
            'memory_markdown': memory_markdown,
            'priority': priority,
            'last_message_lang': _language_hint_for(last_text),
            'last_message_translated': _maybe_translate_for_user(config, user_id, last_text),
            'pinned': user_id in pinned,
        })
    return results

def _infer_priority(memory_markdown: str) -> str:
    if not memory_markdown:
        return 'normal'
    return 'high' if '不舒服' in memory_markdown or 'emotionally vulnerable' in memory_markdown else 'normal'


def _language_hint_for(text: str) -> str:
    if not text:
        return 'Unknown'
    if re.search(r'[\u0E80-\u0EFF]', text):
        return 'Lao'
    if re.search(r'[\u0E00-\u0E7F]', text):
        return 'Thai'
    if re.search(r'[\u4E00-\u9FFF]', text):
        return 'Chinese'
    if re.search(r'[A-Za-z]', text):
        return 'Latin'
    return 'Unknown'


def _translation_worker(config: AppConfig) -> _Rewriter:
    return _Rewriter(config, lambda *args, **kwargs: None)


def _ensure_message_translations(config: AppConfig, user_id: str, items: list[dict[str, Any]]) -> None:
    """Backfill missing translations in the on-disk cache.

    Best-effort, fail-soft. The /api/conversations/{user_id} response
    always includes the current cached `translated` value; clients can
    re-poll the endpoint to pick up newly translated messages.
    """
    if not items:
        return
    auto = bool(config.web_settings.get('message_ops', {}).get('auto_translate', True))
    if not auto:
        return
    cached = load_many(config.paths.memory_dir, user_id, [int(m['message_id']) for m in items if m.get('message_id') is not None])
    pending: dict[str, dict[str, Any]] = {}
    worker = _translation_worker(config)
    for m in items:
        mid = m.get('message_id')
        if mid is None:
            continue
        content = m.get('content') or ''
        source_lang = _language_hint_for(content)
        if source_lang in ('Chinese', 'Unknown'):
            continue
        if str(mid) in cached and cached[str(mid)]:
            continue
        zh = worker.translate_to_zh(content, source_lang)
        if not zh or zh == content:
            continue
        pending[str(mid)] = {
            'source_lang': source_lang,
            'source_text': content[:200],
            'zh': zh,
        }
    if pending:
        bulk_put(config.paths.memory_dir, user_id, pending)


def _auto_translate_enabled(config: AppConfig) -> bool:
    """Plugin + user setting: both must be on for in-app translation."""
    plugin_state = config.web_settings.get('plugins') or {}
    if not bool(plugin_state.get('auto_translate', True)):
        return False
    return bool(config.web_settings.get('message_ops', {}).get('auto_translate', True))


def _maybe_translate_for_user(config: AppConfig, user_id: str, text: str) -> str | None:
    """Quick translation lookup for short previews (no model call).

    Used by list previews so the chat list shows the Chinese version
    of the last message even if the corresponding message_id is not
    loaded. Returns None if not in cache or auto-translate is off.
    """
    if not text:
        return None
    source_lang = _language_hint_for(text)
    if source_lang in ('Chinese', 'Unknown'):
        return None
    if not _auto_translate_enabled(config):
        return None
    data = load_translations(config.paths.memory_dir, user_id)
    items = data.get('items', {})
    for entry in items.values():
        if entry.get('source_text') == text[:200]:
            return entry.get('zh')
    return None


def _attach_translations(config: AppConfig, user_id: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    auto = _auto_translate_enabled(config)
    if not auto or not messages:
        return [{**m, 'translated': None, 'lang': _language_hint_for(m.get('content') or '')} for m in messages]
    _ensure_message_translations(config, user_id, messages)
    cached = load_many(
        config.paths.memory_dir,
        user_id,
        [int(m['message_id']) for m in messages if m.get('message_id') is not None],
    )
    out: list[dict[str, Any]] = []
    for m in messages:
        lang = _language_hint_for(m.get('content') or '')
        translated = None
        mid = m.get('message_id')
        if mid is not None and lang not in ('Chinese', 'Unknown'):
            entry = cached.get(str(mid))
            if entry:
                translated = entry.get('zh')
        out.append({**m, 'lang': lang, 'translated': translated})
    return out


def _dashboard_stats(conversations: list[dict[str, Any]], config: AppConfig) -> dict[str, Any]:
    total = len(conversations)
    high_priority = sum(1 for c in conversations if c['priority'] == 'high')
    total_messages = sum(int(c['message_count']) for c in conversations)
    active_channels = [c for c in config.forwarding_channels if c.get('enabled')]
    return {
        'total_conversations': total,
        'high_priority_conversations': high_priority,
        'total_messages': total_messages,
        'active_admin_channels': len(active_channels),
        'channel_names': [c.get('name') for c in active_channels],
    }


def _is_authenticated(config: AppConfig, request: Request) -> bool:
    if not bool(config.web_settings.get('auth_required', True)):
        return True
    auth = config.web_settings.get('auth') or {}
    sessions = config.web_settings.get('sessions') or {}
    token = request.headers.get('x-session-token', '')
    if not auth or not token:
        return False
    session = sessions.get(token)
    if not isinstance(session, dict):
        return False
    expires_at = float(session.get('expires_at') or 0)
    if time.time() >= expires_at:
        sessions.pop(token, None)
        config.web_settings['sessions'] = sessions
        save_json(config.paths.web_settings_file, config.web_settings)
        return False
    return True


def _check_login_rate_limit(config: AppConfig, request: Request) -> None:
    policy = config.web_settings.get('auth_policy') or {}
    max_attempts = int(policy.get('max_attempts', 5))
    window_seconds = int(policy.get('window_seconds', 300))
    ip = (request.client.host if request.client else 'unknown') or 'unknown'
    login_attempts = dict(config.web_settings.get('login_attempts') or {})
    now = time.time()
    attempts = [float(ts) for ts in login_attempts.get(ip, []) if now - float(ts) < window_seconds]
    if len(attempts) >= max_attempts:
        raise HTTPException(status_code=429, detail='Too many login attempts, try again later')
    attempts.append(now)
    login_attempts[ip] = attempts
    config.web_settings['login_attempts'] = login_attempts
    save_json(config.paths.web_settings_file, config.web_settings)


def _clear_login_attempts(config: AppConfig, request: Request) -> None:
    ip = (request.client.host if request.client else 'unknown') or 'unknown'
    login_attempts = dict(config.web_settings.get('login_attempts') or {})
    if ip in login_attempts:
        login_attempts.pop(ip, None)
        config.web_settings['login_attempts'] = login_attempts
        save_json(config.paths.web_settings_file, config.web_settings)



def _platform_catalog() -> list[dict[str, Any]]:
    return [
        {'platform': 'whatsapp', 'label': 'WhatsApp', 'category': 'chat', 'login_type': 'qr', 'setup_command': 'hermes -p <profile> whatsapp'},
        {'platform': 'telegram', 'label': 'Telegram', 'category': 'chat', 'login_type': 'manual', 'setup_command': 'hermes -p <profile> telegram'},
        {'platform': 'slack', 'label': 'Slack', 'category': 'team', 'login_type': 'manual', 'setup_command': 'hermes -p <profile> slack'},
        {'platform': 'discord', 'label': 'Discord', 'category': 'community', 'login_type': 'manual', 'setup_command': 'hermes -p <profile> discord'},
    ]


def _slugify_workspace_value(value: str) -> str:
    slug = re.sub(r'[^a-z0-9]+', '-', value.strip().lower()).strip('-')
    return slug or 'workspace'


def _sanitize_workspace_input(payload: dict[str, Any], *, workspace_id: str | None = None) -> dict[str, Any]:
    platform = _slugify_workspace_value(str(payload.get('platform') or 'whatsapp'))
    raw_profile = str(payload.get('profile') or payload.get('id') or workspace_id or f'{platform}-workspace').strip()
    profile = _slugify_workspace_value(raw_profile)
    workspace_key = _slugify_workspace_value(str(workspace_id or payload.get('id') or profile))
    label = str(payload.get('label') or workspace_key).strip() or workspace_key
    profile_path = str(payload.get('profile_path') or f'/root/.hermes/profiles/{profile}').strip()
    return {
        'id': workspace_key,
        'label': label,
        'platform': platform,
        'profile': profile,
        'profile_path': profile_path,
        'enabled': bool(payload.get('enabled', True)),
        'primary': bool(payload.get('primary', False)),
    }


def _workspace_entries(config: AppConfig) -> list[dict[str, Any]]:
    return [item for item in (config.web_settings.get('workspaces') or []) if isinstance(item, dict)]


def _save_workspaces(config: AppConfig, items: list[dict[str, Any]]) -> None:
    config.web_settings['workspaces'] = items
    save_json(config.paths.web_settings_file, config.web_settings)


def _workspace_status(config: AppConfig) -> list[dict[str, Any]]:
    catalog = {item['platform']: item for item in _platform_catalog()}
    out: list[dict[str, Any]] = []
    for raw_item in _workspace_entries(config):
        item = _sanitize_workspace_input(raw_item, workspace_id=str(raw_item.get('id') or ''))
        platform = item['platform']
        profile = item['profile']
        profile_path = Path(item['profile_path'])
        meta = catalog.get(platform, {})
        status = 'not_configured'
        try:
            exists = profile_path.exists()
        except PermissionError:
            exists = False
        if exists:
            status = 'configured'
            try:
                running = (profile_path / 'gateway.pid').exists()
            except PermissionError:
                running = False
            if running:
                status = 'running'
        connect_command = str(meta.get('setup_command') or '').replace('<profile>', profile)
        out.append({
            **item,
            'status': status,
            'login_type': meta.get('login_type') or 'manual',
            'connect_command': connect_command,
            'setup_command': connect_command,
        })
    return out


class DisabledBridgeClient:
    """Bridge V2 未安全配置时的 fail-closed 实现。列表仍可读取，写操作明确失败。"""

    @staticmethod
    def _disabled(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise BridgeError(
            'bridge_not_configured',
            'WhatsApp Bridge V2 is not configured',
            retryable=False,
            status_code=503,
        )

    create_account = _disabled
    connect = _disabled
    qr = _disabled
    logout = _disabled
    stop = _disabled
    delete = _disabled


def build_app(
    profile: str | Path | None = None,
    web_dist: str | Path | None = None,
    account_session_factory: sessionmaker[Session] | None = None,
    account_bridge: BridgeProtocol | None = None,
    internal_event_token: str | None = None,
) -> FastAPI:
    config = AppConfig.from_profile(profile)
    db = StateDB(config.paths.db)

    # ---------- 运行时 AI 设置（必须在 AdminRouter/Rewriter 之前初始化 ----------
    runtime_ai_mgr = setup_ai_runtime_settings(config.ai_settings)

    router = AdminRouter(config)
    # 将运行时设置管理器注入 Provider，下次 AI 请求立即使用新配置
    provider = router.rewriter.ai_service.provider
    if isinstance(provider, WendingAIProvider):
        provider.set_runtime_manager(runtime_ai_mgr)

    forwarder = AdminForwarder(config)
    refresher = MemoryRefresher(config)
    frontend_dist = _resolve_frontend_dist(web_dist)

    # ---------- 热刷新函数（供 POST /api/v1/ai/settings 调用）----------
    def _refresh_ai_provider_runtime() -> None:
        # RuntimeAISettingsManager 在 save_to_db() 后已更新内存副本，
        # 此处只需确认 Provider 已持有最新引用（实际上已经持有，因为是同一个 mgr）
        pass

    # ---------------- Plugin center (declared up-front so other endpoints can read flags) ----------------
    PLUGIN_CATALOG = [
        {
            'id': 'auto_translate',
            'name': 'Auto translate',
            'description': 'Translate non-Chinese inbound messages in real time.',
            'category': 'messaging',
            'builtin': True,
            'hooks': ['/api/conversations/{user_id}/messages', '/api/dashboard'],
            'status_when_on': '实时翻译开启',
        },
        {
            'id': 'quick_reply',
            'name': 'Quick reply',
            'description': 'AI-drafted reply suggestions for the active conversation.',
            'category': 'messaging',
            'builtin': True,
            'hooks': ['/api/reply?preview_only=true'],
            'status_when_on': '预览生成已启用',
        },
        {
            'id': 'broadcast',
            'name': 'Mass broadcast',
            'description': 'Send the same message to many contacts at once.',
            'category': 'productivity',
            'builtin': True,
            'hooks': ['POST /api/broadcast'],
            'status_when_on': '群发接口可用',
        },
        {
            'id': 'schedule',
            'name': 'Scheduled send',
            'description': 'Schedule a message to be sent at a specific time.',
            'category': 'productivity',
            'builtin': True,
            'hooks': ['GET/POST/DELETE /api/schedule'],
            'status_when_on': '可创建/查看/删除定时任务',
        },
        {
            'id': 'memory',
            'name': 'Conversation memory',
            'description': 'Persist per-contact summaries and language hints.',
            'category': 'memory',
            'builtin': True,
            'hooks': ['GET /api/memory', 'POST /api/memory/refresh'],
            'status_when_on': '画像会随对话自动更新',
        },
        {
            'id': 'voice_tts',
            'name': 'Voice playback (TTS)',
            'description': 'Speak messages aloud for hands-free review.',
            'category': 'productivity',
            'builtin': True,
            'hooks': [],
            'status_when_on': '需要本地 TTS 客户端配合',
        },
        {
            'id': 'media_pack',
            'name': 'Media pack',
            'description': 'Image, voice, and document handling for richer replies.',
            'category': 'media',
            'builtin': True,
            'hooks': [],
            'status_when_on': '媒体类型回复需配置 Hermes 端',
        },
        {
            'id': 'analytics',
            'name': 'Analytics dashboard',
            'description': 'Per-conversation reply and response-time stats.',
            'category': 'analytics',
            'builtin': True,
            'hooks': ['GET /api/dashboard'],
            'status_when_on': '总览卡片展示插件开关数',
        },
        {
            'id': 'auto_tag',
            'name': 'Auto tag',
            'description': 'Tag conversations by topic, urgency, or language.',
            'category': 'messaging',
            'builtin': True,
            'hooks': [],
            'status_when_on': '基于对话主题自动加标签',
        },
        {
            'id': 'followup',
            'name': 'Follow-up reminders',
            'description': 'Auto-suggest a follow-up message when a chat goes quiet.',
            'category': 'productivity',
            'builtin': True,
            'hooks': [],
            'status_when_on': '长时间无回复时给出跟进建议',
        },
    ]

    def _plugin_state() -> dict[str, bool]:
        state = config.web_settings.get('plugins')
        if not isinstance(state, dict):
            state = {p['id']: True for p in PLUGIN_CATALOG}
            config.web_settings['plugins'] = state
        for p in PLUGIN_CATALOG:
            state.setdefault(p['id'], True)
        return state

    def _plugin_flag(plugin_id: str) -> bool:
        return bool(_plugin_state().get(plugin_id, True))

    app = FastAPI(title='WhatsApp Chat System API', version='0.5.2')
    app.add_middleware(
        CORSMiddleware,
        allow_origins=['*'],
        allow_credentials=False,
        allow_methods=['*'],
        allow_headers=['*'],
    )

    resolved_account_factory = account_session_factory or create_session_factory(create_engine())
    if account_bridge is not None:
        resolved_account_bridge = account_bridge
    else:
        bridge_token = (os.getenv('WHATSAPP_BRIDGE_INTERNAL_TOKEN') or '').strip()
        if bridge_token:
            resolved_account_bridge = BridgeClient(
                base_url=os.getenv('WHATSAPP_BRIDGE_V2_URL', 'http://127.0.0.1:3100'),
                internal_token=bridge_token,
            )
        else:
            resolved_account_bridge = DisabledBridgeClient()
    app.include_router(create_accounts_router(resolved_account_factory, resolved_account_bridge))
    app.include_router(create_conversations_router(resolved_account_factory, resolved_account_bridge))
    resolved_event_token = (
        internal_event_token
        if internal_event_token is not None
        else (os.getenv('WHATSAPP_BRIDGE_INTERNAL_TOKEN') or '').strip()
    )
    app.include_router(create_whatsapp_events_router(resolved_account_factory, resolved_event_token))

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(request: Request, exc: RequestValidationError):
        internal_response = whatsapp_validation_exception_handler(request, exc)
        if internal_response is not None:
            return internal_response
        return JSONResponse({'detail': exc.errors()}, status_code=422)

    @app.middleware('http')
    async def request_id_middleware(request: Request, call_next):
        request.state.request_id = request.headers.get('X-Request-ID') or f'req_{secrets.token_hex(16)}'
        response = await call_next(request)
        response.headers['X-Request-ID'] = request.state.request_id
        return response

    @app.middleware('http')
    async def auth_guard(request: Request, call_next):
        if request.method == 'OPTIONS':
            return await call_next(request)
        if not request.url.path.startswith('/api'):
            return await call_next(request)
        if request.url.path in {'/api/health', '/api/login'}:
            return await call_next(request)
        if not _is_authenticated(config, request):
            return JSONResponse({'detail': 'Unauthorized'}, status_code=401)
        return await call_next(request)

    @app.get('/api/health')
    def health() -> dict[str, Any]:
        return {'ok': True, 'profile': str(config.paths.profile), 'ts': time.time(), 'login_enabled': True}

    @app.post('/api/login')
    def login(request: Request, payload: LoginRequest) -> dict[str, Any]:
        _check_login_rate_limit(config, request)
        stored = config.web_settings.get('auth') or {}
        if not verify_password(stored, payload.password):
            raise HTTPException(status_code=401, detail='Invalid password')
        _clear_login_attempts(config, request)
        token = secrets.token_urlsafe(24)
        ttl = int(config.web_settings.get('auth_ttl_seconds') or 86400)
        sessions = dict(config.web_settings.get('sessions') or {})
        sessions[token] = {'issued_at': time.time(), 'expires_at': time.time() + ttl}
        config.web_settings['sessions'] = sessions
        save_json(config.paths.web_settings_file, config.web_settings)
        return {'success': True, 'session_token': token, 'expires_in': ttl}

    @app.post('/api/logout')
    def logout(request: Request) -> dict[str, Any]:
        token = request.headers.get('x-session-token', '')
        sessions = dict(config.web_settings.get('sessions') or {})
        sessions.pop(token, None)
        config.web_settings['sessions'] = sessions
        save_json(config.paths.web_settings_file, config.web_settings)
        return {'success': True}

    @app.get('/api/dashboard')
    def dashboard() -> dict[str, Any]:
        conversations = _compute_conversation_summaries(config, db)
        return {
            'stats': _dashboard_stats(conversations, config),
            'recent_conversations': conversations[:8],
        }

    @app.get('/api/conversations')
    def conversations(page: int = 1, page_size: int = 50) -> dict[str, Any]:
        page = max(1, page)
        page_size = max(1, min(200, page_size))
        all_items = _compute_conversation_summaries(config, db)
        start = (page - 1) * page_size
        end = start + page_size
        items = all_items[start:end]
        return {
            'items': items,
            'page': page,
            'page_size': page_size,
            'total': len(all_items),
            'has_more': end < len(all_items),
        }

    @app.get('/api/search')
    def search(q: str = '', limit: int = 30) -> dict[str, Any]:
        q = (q or '').strip()
        if not q:
            return {'q': q, 'results': []}
        limit = max(1, min(100, limit))
        hidden = _hidden_message_ids(config)
        results: list[dict[str, Any]] = []
        for row in db.search_messages(q, limit * 2, config.admin_ids):
            message_id = row['message_id']
            if message_id in hidden:
                continue
            content = row['content'] or ''
            lower = content.lower()
            needle = q.lower()
            idx = lower.find(needle)
            start_idx = max(0, idx - 30) if idx >= 0 else 0
            end_idx = min(len(content), idx + len(q) + 30) if idx >= 0 else min(len(content), 80)
            snippet = content[start_idx:end_idx]
            if start_idx > 0:
                snippet = '…' + snippet
            if end_idx < len(content):
                snippet += '…'
            user_id = str(row['user_id'] or '')
            session_ids = [str(row['session_id'])]
            results.append({
                'message_id': message_id,
                'user_id': user_id,
                'user_name': _name_for_user(config, user_id, session_ids, str(row['title'] or '')),
                'role': row['role'],
                'timestamp': row['timestamp'],
                'snippet': snippet,
                'content': content[:200],
            })
            if len(results) >= limit:
                break
        return {'q': q, 'results': results}

    @app.get('/api/conversations/{user_id}/messages')
    def conversation_new_messages(user_id: str, after_id: int = 0, limit: int = 100) -> dict[str, Any]:
        after_id = max(0, int(after_id or 0))
        limit = max(1, min(200, int(limit or 100)))
        hidden = _hidden_message_ids(config)
        rows = db.fetch_user_messages_after(user_id, after_id, limit + 1)
        has_more = len(rows) > limit
        rows = rows[:limit]
        messages = [
            {
                'message_id': row['message_id'],
                'session_id': row['session_id'],
                'role': row['role'],
                'content': row['content'] or '',
                'timestamp': row['timestamp'],
                'platform_message_id': row['platform_message_id'],
                'hidden': row['message_id'] in hidden,
            }
            for row in rows
        ]
        messages = _attach_translations(config, user_id, messages)
        return {
            'user_id': user_id,
            'messages': messages,
            'count': len(messages),
            'next_after_id': max((int(m['message_id']) for m in messages), default=after_id),
            'max_message_id': max((int(m['message_id']) for m in messages), default=after_id),
            'has_more': has_more,
        }

    @app.get('/api/conversations/{user_id}')
    def conversation_detail(user_id: str, page: int = 1, page_size: int = 80) -> dict[str, Any]:
        page = max(1, page)
        page_size = max(1, min(500, page_size))
        offset = (page - 1) * page_size
        hidden = _hidden_message_ids(config)
        rows = db.fetch_user_messages(user_id, page_size, offset)
        if not rows and page == 1:
            raise HTTPException(status_code=404, detail='Conversation not found')
        sessions = db.fetch_sessions()
        session_ids = [sid for sid, session in sessions.items() if str(session.get('user_id') or '') == user_id]
        user_name = _name_for_user(config, user_id, session_ids)
        user_messages = [
            {
                'message_id': row['message_id'],
                'session_id': row['session_id'],
                'role': row['role'],
                'content': row['content'] or '',
                'timestamp': row['timestamp'],
                'platform_message_id': row['platform_message_id'],
                'hidden': row['message_id'] in hidden,
            }
            for row in rows
        ]
        total = db.count_user_messages(user_id)
        page_slice = _attach_translations(config, user_id, user_messages)
        memory_text = _load_memory_markdown(config, user_id)
        sidecar = read_sidecar(user_id, config.paths.memory_dir) or {}
        priority = sidecar.get('priority') or _infer_priority(memory_text)
        language_hint = sidecar.get('preferred_language') or (
            'Lao' if 'Preferred language: Lao' in memory_text else
            ('Thai' if 'Preferred language: Thai' in memory_text else 'Unknown')
        )
        auto_translate = bool(config.web_settings.get('message_ops', {}).get('auto_translate', True))
        hidden_count = db.count_user_hidden_messages(user_id, hidden)
        return {
            'user_id': user_id,
            'user_name': user_name,
            'session_ids': session_ids,
            'messages': page_slice,
            'memory_markdown': memory_text,
            'page': page,
            'page_size': page_size,
            'total_messages': total,
            'hidden_message_count': hidden_count,
            'visible_message_count': max(0, total - hidden_count),
            'has_more': offset + page_size < total,
            'auto_translate': auto_translate,
            'profile_summary': {
                'priority': priority,
                'language_hint': language_hint,
            },
        }

    @app.post('/api/reply')
    def reply(request: ReplyRequest) -> Any:
        # quick_reply plugin: when off, refuse to generate AI previews
        if request.preview_only and not _plugin_state().get('quick_reply', True):
            return {
                'success': False,
                'code': 'plugin_disabled',
                'detail': 'Quick reply plugin is disabled in Plugin Center',
                'plugin': 'quick_reply',
                'preview_only': True,
                'rewrite': None,
            }
        try:
            prepared = router.prepare_reply(request.target, request.message, request.mode)
        except ValueError as exc:
            if str(exc) == 'target_not_found':
                raise HTTPException(status_code=404, detail='Target not found')
            raise HTTPException(status_code=400, detail=str(exc))
        preview_payload = {
            'target': prepared['target'],
            'rewrite': {
                'language': prepared['rewrite'].language,
                'message': prepared['rewrite'].message,
                'used_fallback': prepared['rewrite'].used_fallback,
                'error': prepared['rewrite'].error,
            },
            'mode': request.mode,
            'source_text': request.message,
            'memory_markdown': prepared['memory_markdown'][:2000],
            'profile_sidecar': prepared.get('profile_sidecar') or {},
            'reply_overrides': prepared.get('reply_overrides') or {},
        }
        if request.preview_only:
            if prepared['rewrite'].error:
                return {
                    'success': False,
                    **preview_payload,
                    'preview_only': True,
                    'error': prepared['rewrite'].error,
                }
            return {'success': True, **preview_payload, 'preview_only': True}
        result = router.send_prepared_reply(prepared['target'], prepared['rewrite'], request.message, request.mode)
        if result.get('success') is not True:
            logger.warning('Message delivery failed for target=%s: %s', prepared['target'], result.get('error') or 'unknown error')
            return JSONResponse(
                {
                    'detail': 'Message delivery failed',
                    'code': 'delivery_failed',
                    'retryable': True,
                },
                status_code=502,
            )
        target_id = str((prepared.get('target') or {}).get('id') or request.target)
        platform_message_id = str(result.get('message_id') or '').strip() or None
        result['local_message_id'] = db.append_assistant_message(
            target_id,
            str((result.get('rewrite') or {}).get('message') or prepared['rewrite'].message),
            platform_message_id=platform_message_id,
        )
        result['memory_markdown'] = prepared['memory_markdown'][:2000]
        result['preview_only'] = False
        return result

    @app.get('/api/workspaces')
    def list_workspaces() -> dict[str, Any]:
        return {'items': _workspace_status(config), 'platform_catalog': _platform_catalog()}

    @app.post('/api/workspaces')
    def create_workspace(request: WorkspaceCreateRequest) -> dict[str, Any]:
        items = _workspace_entries(config)
        workspace = _sanitize_workspace_input(request.model_dump(exclude_none=True))
        if any(str(item.get('id') or '') == workspace['id'] for item in items):
            raise HTTPException(status_code=409, detail='Workspace already exists')
        if workspace['primary']:
            for item in items:
                item['primary'] = False
        items.append(workspace)
        _save_workspaces(config, items)
        return {'success': True, 'workspace': _workspace_status(config)[-1]}

    @app.put('/api/workspaces/{workspace_id}')
    def update_workspace(workspace_id: str, request: WorkspaceUpdateRequest) -> dict[str, Any]:
        items = _workspace_entries(config)
        updated = None
        for index, item in enumerate(items):
            if str(item.get('id') or '') != workspace_id:
                continue
            merged = dict(item)
            for key, value in request.model_dump(exclude_none=True).items():
                merged[key] = value
            updated = _sanitize_workspace_input(merged, workspace_id=workspace_id)
            items[index] = updated
            break
        if updated is None:
            raise HTTPException(status_code=404, detail='Workspace not found')
        if updated['primary']:
            for item in items:
                if str(item.get('id') or '') != workspace_id:
                    item['primary'] = False
        _save_workspaces(config, items)
        for item in _workspace_status(config):
            if item['id'] == workspace_id:
                return {'success': True, 'workspace': item}
        raise HTTPException(status_code=404, detail='Workspace not found')

    @app.delete('/api/workspaces/{workspace_id}')
    def delete_workspace(workspace_id: str) -> dict[str, Any]:
        items = _workspace_entries(config)
        remaining = [item for item in items if str(item.get('id') or '') != workspace_id]
        if len(remaining) == len(items):
            raise HTTPException(status_code=404, detail='Workspace not found')
        if remaining and not any(bool(item.get('primary')) for item in remaining):
            remaining[0]['primary'] = True
        _save_workspaces(config, remaining)
        return {'success': True, 'deleted': workspace_id, 'items': _workspace_status(config)}

    @app.get('/api/settings')
    def settings() -> dict[str, Any]:
        safe_web_settings = dict(config.web_settings)
        safe_web_settings.pop('auth', None)
        safe_web_settings.pop('sessions', None)
        safe_web_settings.pop('login_attempts', None)
        account_model = str((config.web_settings.get('reply') or {}).get('ai_model') or '').strip()
        effective_model = account_model or config.ai_settings.default_model
        model_source = 'account_profile' if account_model else 'global_default'
        return {
            'channels': config.forwarding_channels,
            'aliases': load_json(config.paths.alias_file, {}),
            'profile': str(config.paths.profile),
            'platform_catalog': _platform_catalog(),
            'workspaces': _workspace_status(config),
            'web_settings': safe_web_settings,
            'model': {
                'provider': 'wendingai',
                'default': config.ai_settings.default_model,
                'base_url': config.ai_settings.base_url,
                'api_key_configured': bool(config.ai_settings.api_key),
                'effective_model': effective_model,
                'model_source': model_source,
            },
            'plugins': _plugin_state(),
        }

    @app.get('/api/v1/ai/settings')
    def ai_settings() -> dict[str, Any]:
        """返回当前有效 AI 配置（不含密钥明文）。"""
        try:
            mgr = get_runtime_ai_settings()
            return mgr.to_safe_dict()
        except RuntimeError:
            # 降级：使用原始 env 配置
            return {
                **config.ai_settings.safe_dict(),
                'api_key_hint': None,
            }

    @app.put('/api/v1/ai/settings')
    def update_ai_settings(request: AISettingsUpdateRequest) -> dict[str, Any]:
        """更新 AI 运行配置；密钥自动加密存储，保存后立即生效。"""
        try:
            mgr = get_runtime_ai_settings()
            saved = mgr.save_to_db(
                base_url=request.base_url,
                default_model=request.default_model,
                api_key=request.api_key,
                timeout_seconds=request.timeout_seconds,
                max_retries=request.max_retries,
            )
            # 刷新 AI Provider 的运行时配置（热生效）
            _refresh_ai_provider_runtime()
            return {'success': True, **saved}
        except RuntimeError:
            raise HTTPException(status_code=500, detail='AI settings not initialised')

    @app.put('/api/settings')
    def update_settings(request: SettingsUpdateRequest) -> dict[str, Any]:
        payload = [item.model_dump() for item in request.channels]
        save_json(config.paths.admin_channels_file, payload)
        config.forwarding_channels = payload
        if request.web_settings:
            merged = dict(config.web_settings)
            for key, value in request.web_settings.items():
                if isinstance(value, dict) and isinstance(merged.get(key), dict):
                    merged[key] = {**merged[key], **value}
                else:
                    merged[key] = value
            if request.password:
                merged['auth'] = build_password_record(request.password)
            config.web_settings = merged
            save_json(config.paths.web_settings_file, config.web_settings)
        elif request.password:
            config.web_settings['auth'] = build_password_record(request.password)
            save_json(config.paths.web_settings_file, config.web_settings)
        return {'success': True, 'channels': payload}

    @app.post('/api/messages/{message_id}/translate')
    def translate_message(message_id: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        body = body or {}
        user_id = str(body.get('user_id') or '')
        text = str(body.get('content') or '')
        if not user_id or not text:
            raise HTTPException(status_code=400, detail='user_id and content required')
        public_message_id: int | str = int(message_id) if message_id.isdigit() else message_id
        lang = _language_hint_for(text)
        if lang in ('Chinese', 'Unknown'):
            return {'message_id': public_message_id, 'lang': lang, 'translated': None}
        worker = _translation_worker(config)
        translated = worker.translate_to_zh_result(text, lang)
        if translated.message and translated.message != text:
            put_translation(config.paths.memory_dir, user_id, message_id, {
                'source_lang': lang,
                'source_text': text[:200],
                'zh': translated.message,
            })
        payload = {
            'message_id': public_message_id,
            'lang': lang,
            'translated': translated.message or None,
        }
        if translated.error:
            return {
                'success': False,
                **payload,
                'translated': None,
                'fallback_text': translated.message or text,
                'used_fallback': translated.used_fallback,
                'error': translated.error,
            }
        return payload

    @app.post('/api/messages/hide')
    def hide_messages(payload: dict[str, Any]) -> dict[str, Any]:
        if not _hide_messages_enabled(config):
            raise HTTPException(status_code=403, detail='Message hiding is disabled')
        ids = payload.get('message_ids') or []
        existing = list(config.web_settings.get('hidden_message_ids') or [])
        existing_set = set(existing)
        for item in ids:
            existing_set.add(item)
        config.web_settings['hidden_message_ids'] = sorted(existing_set)
        save_json(config.paths.web_settings_file, config.web_settings)
        return {'success': True, 'hidden_message_ids': config.web_settings['hidden_message_ids'], 'remote_delete_supported': False}

    @app.post('/api/jobs/run')
    def run_job(request: JobRunRequest) -> dict[str, Any]:
        if request.job == 'router':
            code = router.run()
        elif request.job == 'forward':
            code = forwarder.run()
        elif request.job == 'refresh-memory':
            code = refresher.run()
        else:
            raise HTTPException(status_code=400, detail='Unknown job')
        return {'success': code == 0, 'job': request.job, 'exit_code': code}

    # ---------------- Chat list ops (pin / hide / delete) ----------------
    def _chat_ops() -> dict[str, Any]:
        ops = config.web_settings.get('chat_ops')
        if not isinstance(ops, dict):
            ops = {'pinned': [], 'hidden': [], 'deleted': []}
            config.web_settings['chat_ops'] = ops
        ops.setdefault('pinned', [])
        ops.setdefault('hidden', [])
        ops.setdefault('deleted', [])
        return ops

    @app.post('/api/chat/pin')
    def chat_pin(payload: dict[str, Any]) -> dict[str, Any]:
        user_id = str(payload.get('user_id') or '')
        pinned = bool(payload.get('pinned', True))
        if not user_id:
            raise HTTPException(status_code=400, detail='user_id required')
        ops = _chat_ops()
        current = [str(x) for x in ops['pinned']]
        if pinned and user_id not in current:
            current.insert(0, user_id)
        elif not pinned:
            current = [x for x in current if x != user_id]
        ops['pinned'] = current
        save_json(config.paths.web_settings_file, config.web_settings)
        return {'success': True, 'pinned': current}

    @app.post('/api/chat/delete')
    def chat_delete(payload: dict[str, Any]) -> dict[str, Any]:
        user_id = str(payload.get('user_id') or '')
        if not user_id:
            raise HTTPException(status_code=400, detail='user_id required')
        ops = _chat_ops()
        deleted = [str(x) for x in ops.get('deleted', []) if x != user_id]
        deleted.append(user_id)
        ops['deleted'] = deleted[-200:]
        ops['pinned'] = [x for x in ops.get('pinned', []) if x != user_id]
        save_json(config.paths.web_settings_file, config.web_settings)
        return {'success': True, 'deleted': ops['deleted']}

    @app.post('/api/chat/restore')
    def chat_restore(payload: dict[str, Any]) -> dict[str, Any]:
        user_id = str(payload.get('user_id') or '')
        if not user_id:
            raise HTTPException(status_code=400, detail='user_id required')
        ops = _chat_ops()
        ops['deleted'] = [x for x in ops.get('deleted', []) if x != user_id]
        save_json(config.paths.web_settings_file, config.web_settings)
        return {'success': True, 'deleted': ops['deleted']}

    # ---------------- Scheduled message ----------------
    @app.get('/api/schedule')
    def list_schedule() -> dict[str, Any]:
        items = config.web_settings.get('schedule') or []
        items = sorted([i for i in items if isinstance(i, dict)], key=lambda i: float(i.get('run_at') or 0))
        return {'items': items}

    @app.post('/api/schedule')
    def add_schedule(request: ScheduleRequest) -> dict[str, Any]:
        if not request.target or not request.message:
            raise HTTPException(status_code=400, detail='target and message required')
        if request.run_at <= 0:
            raise HTTPException(status_code=400, detail='run_at must be a future timestamp')
        items = list(config.web_settings.get('schedule') or [])
        entry = {
            'id': f"sch-{int(time.time()*1000)}",
            'target': request.target,
            'message': request.message,
            'run_at': float(request.run_at),
            'mode': request.mode,
            'use_memory': request.use_memory,
            'status': 'pending',
            'created_at': time.time(),
        }
        items.append(entry)
        config.web_settings['schedule'] = items
        save_json(config.paths.web_settings_file, config.web_settings)
        return {'success': True, 'item': entry, 'items': items}

    @app.delete('/api/schedule/{schedule_id}')
    def delete_schedule(schedule_id: str) -> dict[str, Any]:
        current = list(config.web_settings.get('schedule') or [])
        if not any(str(i.get('id')) == schedule_id for i in current if isinstance(i, dict)):
            raise HTTPException(status_code=404, detail='Scheduled message not found')
        items = [i for i in current if str(i.get('id')) != schedule_id]
        config.web_settings['schedule'] = items
        save_json(config.paths.web_settings_file, config.web_settings)
        return {'success': True, 'items': items}

    # ---------------- Broadcast (mass send) ----------------
    @app.post('/api/broadcast')
    def broadcast(request: BroadcastRequest) -> dict[str, Any]:
        if not request.targets:
            raise HTTPException(status_code=400, detail='targets required')
        if not request.message:
            raise HTTPException(status_code=400, detail='message required')
        results = []
        for target in request.targets:
            try:
                prepared = router.prepare_reply(target, request.message, request.mode)
                sent = router.send_prepared_reply(prepared['target'], prepared['rewrite'], request.message, request.mode)
                ok = sent.get('success') is True
                results.append({
                    'target': target,
                    'success': ok,
                    'message': sent.get('rewrite', {}).get('message') if ok else None,
                    'error': None if ok else 'Message delivery failed',
                    'retryable': not ok,
                })
            except Exception as exc:  # noqa: BLE001
                results.append({'target': target, 'success': False, 'error': str(exc)})
        log = list(config.web_settings.get('broadcast_log') or [])
        entry = {
            'id': f"bc-{int(time.time()*1000)}",
            'targets': request.targets,
            'message': request.message,
            'mode': request.mode,
            'results': results,
            'created_at': time.time(),
        }
        log.append(entry)
        config.web_settings['broadcast_log'] = log[-30:]
        save_json(config.paths.web_settings_file, config.web_settings)
        succeeded = sum(1 for item in results if item.get('success') is True)
        failed = len(results) - succeeded
        return {
            'success': failed == 0,
            'partial_success': succeeded > 0 and failed > 0,
            'total': len(results),
            'succeeded': succeeded,
            'failed': failed,
            'entry': entry,
        }

    @app.get('/api/broadcast')
    def list_broadcast() -> dict[str, Any]:
        items = list(config.web_settings.get('broadcast_log') or [])
        items = sorted([i for i in items if isinstance(i, dict)], key=lambda i: float(i.get('created_at') or 0), reverse=True)
        return {'items': items[:30]}

    # ---------------- Plugin center (PLUGIN_CATALOG / _plugin_state / _plugin_flag are defined near the top of build_app) ----------------
    @app.get('/api/plugins')
    def list_plugins() -> dict[str, Any]:
        state = _plugin_state()
        items = [
            {**p, 'enabled': bool(state.get(p['id'], True))}
            for p in PLUGIN_CATALOG
        ]
        return {'items': items}

    @app.post('/api/plugins/toggle')
    def toggle_plugin(request: PluginToggleRequest) -> dict[str, Any]:
        if not any(p['id'] == request.plugin_id for p in PLUGIN_CATALOG):
            raise HTTPException(status_code=404, detail='Unknown plugin')
        state = _plugin_state()
        state[request.plugin_id] = bool(request.enabled)
        save_json(config.paths.web_settings_file, config.web_settings)
        return {'success': True, 'plugin_id': request.plugin_id, 'enabled': state[request.plugin_id]}

    @app.delete('/api/plugins/{plugin_id}')
    def remove_plugin(plugin_id: str) -> dict[str, Any]:
        state = _plugin_state()
        if plugin_id not in state:
            raise HTTPException(status_code=404, detail='Unknown plugin')
        state[plugin_id] = False
        save_json(config.paths.web_settings_file, config.web_settings)
        return {'success': True, 'plugin_id': plugin_id, 'enabled': False}

    if frontend_dist:
        assets_dir = frontend_dist / 'assets'
        if assets_dir.is_dir():
            app.mount('/assets', StaticFiles(directory=assets_dir, check_dir=True), name='web-assets')

        @app.get('/{full_path:path}', include_in_schema=False)
        def frontend_shell(full_path: str = ''):
            return FileResponse(Path(frontend_dist) / 'index.html')

    return app


try:
    app = build_app()
except PermissionError:
    app = FastAPI(title='WhatsApp Chat System API', version='0.5.2')
