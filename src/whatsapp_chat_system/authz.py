from __future__ import annotations

import time
from typing import Any

from fastapi import HTTPException, Request


def get_current_user_record(runtime: Any, request: Request) -> dict[str, Any]:
    token = request.headers.get("x-session-token", "")
    sessions = dict(runtime.web_settings.get("sessions") or {})
    session = sessions.get(token)
    if not isinstance(session, dict) or not session:
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        expires_at = float(session.get("expires_at") or 0)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Unauthorized") from exc
    if expires_at <= time.time():
        raise HTTPException(status_code=401, detail="Unauthorized")
    username = session.get("username", "admin")
    users: dict[str, Any] = runtime.web_settings.get("users") or {}
    user = dict(users.get(username) or {})
    user.setdefault("username", username)
    user.setdefault("role", "admin" if username == "admin" else "operator")
    user.setdefault("allowed_account_ids", [])
    return user


def require_admin(runtime: Any, request: Request) -> dict[str, Any]:
    user = get_current_user_record(runtime, request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return user


def require_operator(runtime: Any, request: Request) -> dict[str, Any]:
    user = get_current_user_record(runtime, request)
    if user.get("role") not in {"admin", "operator"}:
        raise HTTPException(status_code=403, detail="Operator or admin only")
    return user


def require_object_account_access(
    runtime: Any,
    request: Request,
    account_id: str | None,
    *,
    write: bool = False,
    not_found_detail: str = "Object not found",
) -> dict[str, Any]:
    """Authorize one account-owned object, failing closed for unknown roles/scopes."""
    user = get_current_user_record(runtime, request)
    role = str(user.get("role") or "").strip()
    cleaned_account_id = str(account_id or "").strip()
    if not cleaned_account_id:
        raise HTTPException(status_code=404, detail=not_found_detail)
    if role not in {"admin", "operator", "viewer"}:
        raise HTTPException(status_code=403, detail="Role is not allowed")
    if role != "admin":
        allowed_ids = {
            str(value).strip()
            for value in (user.get("allowed_account_ids") or [])
            if str(value).strip()
        }
        if cleaned_account_id not in allowed_ids:
            # Do not disclose whether an object exists in another account.
            raise HTTPException(status_code=404, detail=not_found_detail)
    if write and role not in {"admin", "operator"}:
        raise HTTPException(status_code=403, detail="Operator or admin only")
    return user


def visible_account_ids_for(runtime: Any, request: Request) -> list[str] | None:
    user = get_current_user_record(runtime, request)
    role = str(user.get("role") or "").strip()
    if role not in {"admin", "operator", "viewer"}:
        raise HTTPException(status_code=403, detail="Role is not allowed")
    if role == "admin":
        return None
    ids = [
        str(x).strip()
        for x in (user.get("allowed_account_ids") or [])
        if str(x).strip()
    ]
    return ids


def restrict_account_id(
    requested_account_id: str, visible_ids: list[str] | None
) -> str:
    if visible_ids is None:
        return requested_account_id
    if requested_account_id == "all":
        return "all"
    if requested_account_id not in visible_ids:
        raise HTTPException(status_code=403, detail="Account not allowed")
    return requested_account_id
