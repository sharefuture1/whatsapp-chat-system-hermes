from __future__ import annotations

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
from .router import AdminRouter
from .storage import StateDB


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


class SettingsUpdateRequest(BaseModel):
    channels: list[ChannelConfig]
    web_settings: dict[str, Any] | None = None
    password: str | None = None


class JobRunRequest(BaseModel):
    job: str


class LoginRequest(BaseModel):
    password: str


def _load_origins(config: AppConfig) -> dict[str, dict[str, Any]]:
    origins_raw = load_json(config.paths.sessions_json, {})
    origins: dict[str, dict[str, Any]] = {}
    for _session_key, rec in origins_raw.items():
        sid = rec.get('session_id')
        if sid:
            origins[sid] = rec.get('origin') or {}
    return origins


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
        if row['timestamp'] >= item['last_timestamp'] and row['session_id'] not in hidden:
            item['last_timestamp'] = row['timestamp']
            item['last_message'] = content
    results = []
    for item in summary.values():
        user_id = item['user_id']
        memory_markdown = _load_memory_markdown(config, user_id)
        results.append({
            **item,
            'languages': sorted(item['languages']),
            'memory_markdown': memory_markdown,
            'priority': 'high' if '不舒服' in memory_markdown or 'emotionally vulnerable' in memory_markdown else 'normal',
        })
    return sorted(results, key=lambda x: x['last_timestamp'], reverse=True)


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
    stored = config.web_settings.get('auth') or {}
    session_token = str(config.web_settings.get('session_token') or '')
    if not stored:
        return True
    token = request.headers.get('x-session-token', '')
    return bool(session_token and token and token == session_token)


def build_app(profile: str | Path = '/root/.hermes/profiles/whatsapp-support') -> FastAPI:
    config = AppConfig.from_profile(profile)
    db = StateDB(config.paths.db)
    router = AdminRouter(config)
    forwarder = AdminForwarder(config)
    refresher = MemoryRefresher(config)

    app = FastAPI(title='WhatsApp Chat System API', version='0.5.0')
    app.add_middleware(
        CORSMiddleware,
        allow_origins=['*'],
        allow_credentials=True,
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
    def login(request: LoginRequest) -> dict[str, Any]:
        stored = config.web_settings.get('auth') or {}
        if not verify_password(stored, request.password):
            raise HTTPException(status_code=401, detail='Invalid password')
        import secrets
        token = secrets.token_urlsafe(24)
        config.web_settings['session_token'] = token
        save_json(config.paths.web_settings_file, config.web_settings)
        return {'success': True, 'session_token': token}

    @app.get('/api/dashboard')
    def dashboard() -> dict[str, Any]:
        conversations = _compute_conversation_summaries(config, db)
        return {
            'stats': _dashboard_stats(conversations, config),
            'recent_conversations': conversations[:8],
        }

    @app.get('/api/conversations')
    def conversations() -> list[dict[str, Any]]:
        return _compute_conversation_summaries(config, db)

    @app.get('/api/conversations/{user_id}')
    def conversation_detail(user_id: str) -> dict[str, Any]:
        sessions = db.fetch_sessions()
        rows = db.fetch_session_messages()
        origins = _load_origins(config)
        hidden = set(config.web_settings.get('hidden_message_ids') or [])
        messages = []
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
            messages.append({
                'message_id': row.get('message_id', None) if isinstance(row, dict) else None,
                'session_id': sid,
                'role': row['role'],
                'content': row['content'] or '',
                'timestamp': row['timestamp'],
                'hidden': row.get('id') in hidden if isinstance(row, dict) else False,
            })
        if not messages:
            raise HTTPException(status_code=404, detail='Conversation not found')
        memory_text = _load_memory_markdown(config, user_id)
        return {
            'user_id': user_id,
            'user_name': user_name,
            'session_ids': session_ids,
            'messages': messages,
            'memory_markdown': memory_text,
            'profile_summary': {
                'priority': 'high' if 'emotionally vulnerable' in memory_text else 'normal',
                'language_hint': 'Lao' if 'Preferred language: Lao' in memory_text else ('Thai' if 'Preferred language: Thai' in memory_text else 'Unknown'),
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
        safe_web_settings.pop('session_token', None)
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
