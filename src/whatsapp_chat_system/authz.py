from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request


def get_current_user_record(runtime: Any, request: Request) -> dict[str, Any]:
    token = request.headers.get('x-session-token', '')
    sessions = dict(runtime.web_settings.get('sessions') or {})
    session = sessions.get(token)
    if not session:
        raise HTTPException(status_code=401, detail='Unauthorized')
    username = session.get('username', 'admin')
    users: dict[str, Any] = runtime.web_settings.get('users') or {}
    user = dict(users.get(username) or {})
    user.setdefault('username', username)
    user.setdefault('role', 'admin' if username == 'admin' else 'operator')
    user.setdefault('allowed_account_ids', [])
    return user


def require_admin(runtime: Any, request: Request) -> dict[str, Any]:
    user = get_current_user_record(runtime, request)
    if user.get('role') != 'admin':
        raise HTTPException(status_code=403, detail='Admin only')
    return user


def visible_account_ids_for(runtime: Any, request: Request) -> list[str] | None:
    user = get_current_user_record(runtime, request)
    if user.get('role') == 'admin':
        return None
    ids = [str(x).strip() for x in (user.get('allowed_account_ids') or []) if str(x).strip()]
    return ids


def restrict_account_id(requested_account_id: str, visible_ids: list[str] | None) -> str:
    if visible_ids is None:
        return requested_account_id
    if requested_account_id == 'all':
        return 'all'
    if requested_account_id not in visible_ids:
        raise HTTPException(status_code=403, detail='Account not allowed')
    return requested_account_id
