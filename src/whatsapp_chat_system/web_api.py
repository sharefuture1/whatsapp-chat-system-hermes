from __future__ import annotations

import secrets
import time
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


def _compute_conversation_summaries(config: AppConfig, db: StateDB) -> list[dict[str, Any]]:
    sessions = db.fetch_sessions()
    rows = db.fetch_session_messages()
    origins = _load_origins(config)
    hidden = set(config.web_settings.get('hidden_message_ids') or [])
    summary: dict[str, dict[str, Any]] = {}
    for row in rows:
        sid = row['session_id']
        session = sessions.get(sid, {})
        origin = origins.get(sid, {})
        user_id = str(session.get('user_id') or origin.get('user_id') or '')
        if not user_id or user_id in config.admin_ids:
            continue
        user_name = str(origin.get('user_name') or origin.get('chat_name') or user_id)
        item = summary.setdefault(user_id, {
            'user_id': user_id,
            'user_name': user_name,
            'session_ids': [],
            'last_timestamp': row['timestamp'],
            'last_message': row['content'] or '',
            'message_count': 0,
            'user_message_count': 0,
            'assistant_message_count': 0,
            'languages': set(),
        })
        if sid not in item['session_ids']:
            item['session_ids'].append(sid)
        item['message_count'] += 1
        if row['role'] == 'user':
            item['user_message_count'] += 1
        elif row['role'] == 'assistant':
            item['assistant_message_count'] += 1
        content = row['content'] or ''
        if any('\u0e80' <= ch <= '\u0eff' for ch in content):
            item['languages'].add('Lao')
        elif any('\u0e00' <= ch <= '\u0e7f' for ch in content):
            item['languages'].add('Thai')
        elif any('\u4e00' <= ch <= '\u9fff' for ch in content):
            item['languages'].add('Chinese')
        elif any('a' <= ch.lower() <= 'z' for ch in content):
            item['languages'].add('Latin')
        if row['timestamp'] >= item['last_timestamp'] and row['message_id'] not in hidden:
            item['last_timestamp'] = row['timestamp']
            item['last_message'] = content
    results = []
    for item in summary.values():
        user_id = item['user_id']
        memory_markdown = _load_memory_markdown(config, user_id)
        sidecar = read_sidecar(user_id, config.paths.memory_dir)
        priority = (sidecar or {}).get('priority') or _infer_priority(memory_markdown)
        results.append({
            **item,
            'languages': sorted(item['languages']),
            'memory_markdown': memory_markdown,
            'priority': priority,
        })
    return sorted(results, key=lambda x: x['last_timestamp'], reverse=True)


def _infer_priority(memory_markdown: str) -> str:
    if not memory_markdown:
        return 'normal'
    return 'high' if '不舒服' in memory_markdown or 'emotionally vulnerable' in memory_markdown else 'normal'


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
        sessions = db.fetch_sessions()
        rows = db.fetch_session_messages()
        origins = _load_origins(config)
        hidden = set(config.web_settings.get('hidden_message_ids') or [])
        needle = q.lower()
        results: list[dict[str, Any]] = []
        for row in rows:
            message_id = row['message_id']
            if message_id in hidden:
                continue
            content = row['content'] or ''
            if needle not in content.lower():
                continue
            sid = row['session_id']
            session = sessions.get(sid, {})
            origin = origins.get(sid, {})
            user_id = str(session.get('user_id') or origin.get('user_id') or '')
            if not user_id or user_id in config.admin_ids:
                continue
            user_name = str(origin.get('user_name') or origin.get('chat_name') or user_id)
            lower = content.lower()
            idx = lower.find(needle)
            start = max(0, idx - 30)
            end = min(len(content), idx + len(q) + 30)
            snippet = content[start:end]
            if idx > 0:
                snippet = '…' + snippet
            if end < len(content):
                snippet = snippet + '…'
            results.append({
                'message_id': message_id,
                'user_id': user_id,
                'user_name': user_name,
                'role': row['role'],
                'timestamp': row['timestamp'],
                'snippet': snippet,
                'content': content[:200],
            })
            if len(results) >= limit:
                break
        return {'q': q, 'results': results}

    @app.get('/api/conversations/{user_id}')
    def conversation_detail(user_id: str, page: int = 1, page_size: int = 50) -> dict[str, Any]:
        page = max(1, page)
        page_size = max(1, min(500, page_size))
        sessions = db.fetch_sessions()
        rows = db.fetch_session_messages()
        origins = _load_origins(config)
        hidden = set(config.web_settings.get('hidden_message_ids') or [])
        user_messages: list[dict[str, Any]] = []
        user_name = user_id
        session_ids: list[str] = []
        for row in rows:
            sid = row['session_id']
            session = sessions.get(sid, {})
            origin = origins.get(sid, {})
            current_user_id = str(session.get('user_id') or origin.get('user_id') or '')
            if current_user_id != user_id:
                continue
            user_name = str(origin.get('user_name') or origin.get('chat_name') or user_id)
            if sid not in session_ids:
                session_ids.append(sid)
            user_messages.append({
                'message_id': row['message_id'],
                'session_id': sid,
                'role': row['role'],
                'content': row['content'] or '',
                'timestamp': row['timestamp'],
                'hidden': row['message_id'] in hidden,
            })
        if not user_messages:
            raise HTTPException(status_code=404, detail='Conversation not found')
        user_messages.sort(key=lambda m: m['timestamp'])
        total = len(user_messages)
        start = (page - 1) * page_size
        end = start + page_size
        messages = user_messages[start:end]
        memory_text = _load_memory_markdown(config, user_id)
        sidecar = read_sidecar(user_id, config.paths.memory_dir) or {}
        priority = sidecar.get('priority') or _infer_priority(memory_text)
        language_hint = sidecar.get('preferred_language') or (
            'Lao' if 'Preferred language: Lao' in memory_text else
            ('Thai' if 'Preferred language: Thai' in memory_text else 'Unknown')
        )
        return {
            'user_id': user_id,
            'user_name': user_name,
            'session_ids': session_ids,
            'messages': messages,
            'memory_markdown': memory_text,
            'page': page,
            'page_size': page_size,
            'total_messages': total,
            'has_more': end < total,
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
