from __future__ import annotations

import secrets
import time
import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .config import AppConfig, build_password_record, load_json, save_json, verify_password
from .forwarder import AdminForwarder
from .memory_refresh import MemoryRefresher
from .origins import OriginsCache
from .router import AdminRouter
from .storage import StateDB
from .structured_profile import read_sidecar
from .translations import bulk_put, load_many, load_translations, put_translation
from .rewriter import Rewriter as _Rewriter  # imported for translation helper below


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


_origins_cache = OriginsCache(ttl_seconds=30)


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


def _compute_conversation_summaries(config: AppConfig, db: StateDB) -> list[dict[str, Any]]:
    rows = db.fetch_conversation_summaries(config.admin_ids)
    results: list[dict[str, Any]] = []
    for row in rows:
        user_id = str(row['user_id'] or '')
        if not user_id:
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
    if not bool(config.web_settings.get('message_ops', {}).get('auto_translate', True)):
        return None
    data = load_translations(config.paths.memory_dir, user_id)
    items = data.get('items', {})
    for entry in items.values():
        if entry.get('source_text') == text[:200]:
            return entry.get('zh')
    return None


def _attach_translations(config: AppConfig, user_id: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    auto = bool(config.web_settings.get('message_ops', {}).get('auto_translate', True))
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


def _workspace_status(config: AppConfig) -> list[dict[str, Any]]:
    catalog = {item['platform']: item for item in _platform_catalog()}
    out: list[dict[str, Any]] = []
    for item in config.web_settings.get('workspaces') or []:
        if not isinstance(item, dict):
            continue
        platform = str(item.get('platform') or 'unknown')
        profile = str(item.get('profile') or item.get('id') or platform)
        profile_path = Path(str(item.get('profile_path') or f'/root/.hermes/profiles/{profile}'))
        meta = catalog.get(platform, {})
        status = 'not_configured'
        if profile_path.exists():
            status = 'configured'
            if (profile_path / 'gateway.pid').exists():
                status = 'running'
        out.append({
            **item,
            'platform': platform,
            'profile': profile,
            'profile_path': str(profile_path),
            'status': status,
            'login_type': meta.get('login_type') or 'manual',
            'setup_command': str(meta.get('setup_command') or '').replace('<profile>', profile),
        })
    return out

def build_app(profile: str | Path = '/root/.hermes/profiles/whatsapp-support') -> FastAPI:
    config = AppConfig.from_profile(profile)
    db = StateDB(config.paths.db)
    router = AdminRouter(config)
    forwarder = AdminForwarder(config)
    refresher = MemoryRefresher(config)

    app = FastAPI(title='WhatsApp Chat System API', version='0.5.2')
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            'http://127.0.0.1:38998',
            'http://127.0.0.1:38999',
            'http://127.0.0.1:5174',
            'https://whats.future1.us',
            'https://www.whats.future1.us',
        ],
        allow_credentials=False,
        allow_methods=['*'],
        allow_headers=['*'],
    )

    @app.middleware('http')
    async def auth_guard(request: Request, call_next):
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
        hidden = set(config.web_settings.get('hidden_message_ids') or [])
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
        hidden = set(config.web_settings.get('hidden_message_ids') or [])
        rows = db.fetch_user_messages_after(user_id, after_id, limit)
        messages = [
            {
                'message_id': row['message_id'],
                'session_id': row['session_id'],
                'role': row['role'],
                'content': row['content'] or '',
                'timestamp': row['timestamp'],
                'hidden': row['message_id'] in hidden,
            }
            for row in rows
        ]
        messages = _attach_translations(config, user_id, messages)
        return {
            'user_id': user_id,
            'messages': messages,
            'count': len(messages),
            'max_message_id': max((int(m['message_id']) for m in messages), default=after_id),
        }

    @app.get('/api/conversations/{user_id}')
    def conversation_detail(user_id: str, page: int = 1, page_size: int = 80) -> dict[str, Any]:
        page = max(1, page)
        page_size = max(1, min(500, page_size))
        offset = (page - 1) * page_size
        hidden = set(config.web_settings.get('hidden_message_ids') or [])
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
    def reply(request: ReplyRequest) -> dict[str, Any]:
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
            },
            'mode': request.mode,
            'source_text': request.message,
            'memory_markdown': prepared['memory_markdown'][:2000],
        }
        if request.preview_only:
            return {'success': True, **preview_payload, 'preview_only': True}
        result = router.send_prepared_reply(prepared['target'], prepared['rewrite'], request.message, request.mode)
        result['memory_markdown'] = prepared['memory_markdown'][:2000]
        result['preview_only'] = False
        return result

    @app.get('/api/settings')
    def settings() -> dict[str, Any]:
        safe_web_settings = dict(config.web_settings)
        safe_web_settings.pop('auth', None)
        safe_web_settings.pop('sessions', None)
        safe_web_settings.pop('login_attempts', None)
        return {
            'channels': config.forwarding_channels,
            'aliases': load_json(config.paths.alias_file, {}),
            'profile': str(config.paths.profile),
            'platform_catalog': _platform_catalog(),
            'workspaces': _workspace_status(config),
            'web_settings': safe_web_settings,
        }

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
    def translate_message(message_id: int, body: dict[str, Any] | None = None) -> dict[str, Any]:
        body = body or {}
        user_id = str(body.get('user_id') or '')
        text = str(body.get('content') or '')
        if not user_id or not text:
            raise HTTPException(status_code=400, detail='user_id and content required')
        lang = _language_hint_for(text)
        if lang in ('Chinese', 'Unknown'):
            return {'message_id': message_id, 'lang': lang, 'translated': None}
        worker = _translation_worker(config)
        zh = worker.translate_to_zh(text, lang)
        if zh and zh != text:
            put_translation(config.paths.memory_dir, user_id, message_id, {
                'source_lang': lang,
                'source_text': text[:200],
                'zh': zh,
            })
        return {'message_id': message_id, 'lang': lang, 'translated': zh or None}

    @app.post('/api/messages/hide')
    def hide_messages(payload: dict[str, Any]) -> dict[str, Any]:
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

    return app


app = build_app()
