"""Multi-user management API: list, register, delete, change-password."""

from __future__ import annotations

import re
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ...standalone_api import (
    _is_authenticated,
    _session_info,
    _verify_password,
    save_runtime_settings,
)
from ...runtime import StandaloneRuntime


# ── Request / Response models ────────────────────────────────────────────────


class UserSummary(BaseModel):
    username: str
    created_at: float | None = None


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=128)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=8, max_length=128)


class DeleteUserRequest(BaseModel):
    username: str


# ── Helpers ───────────────────────────────────────────────────────────────────

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_\-\.]{2,64}$")

_INVALID_USERNAME = (
    "Username must be 2-64 chars: letters, digits, underscore, hyphen, dot"
)


def _list_users(runtime: StandaloneRuntime) -> list[UserSummary]:
    users = runtime.web_settings.get("users") or {}
    return [
        UserSummary(username=name, created_at=record.get("created_at"))
        for name, record in users.items()
    ]


def create_users_router(runtime: StandaloneRuntime) -> APIRouter:
    router = APIRouter(prefix="/api/v1/users", tags=["users"])

    @router.get("", response_model=list[UserSummary])
    def list_users(request: Request) -> list[UserSummary]:
        """List all registered users (username + created_at only)."""
        if not _is_authenticated(runtime, request.headers.get("x-session-token", "")):
            raise HTTPException(status_code=401, detail="Unauthorized")
        return _list_users(runtime)

    @router.post("/register", status_code=201)
    def register_user(request: Request, body: RegisterRequest) -> dict[str, Any]:
        """Register a new operator account (admin only)."""
        if not _is_authenticated(runtime, request.headers.get("x-session-token", "")):
            raise HTTPException(status_code=401, detail="Unauthorized")
        username = body.username.strip()
        if not _USERNAME_RE.match(username):
            raise HTTPException(status_code=422, detail=_INVALID_USERNAME)

        users: dict[str, Any] = runtime.web_settings.get("users") or {}
        if username in users:
            raise HTTPException(status_code=409, detail="Username already exists")

        import hashlib
        import secrets

        salt = secrets.token_hex(16)
        derived = hashlib.pbkdf2_hmac(
            "sha256", body.password.encode(), salt.encode(), 600_000
        )
        now = time.time()
        users[username] = {
            "scheme": "pbkdf2_sha256",
            "salt": salt,
            "iterations": 600_000,
            "hash": derived.hex(),
            "created_at": now,
        }
        runtime.web_settings["users"] = users
        save_runtime_settings(runtime)
        return {"username": username, "created_at": now}

    @router.post("/delete", status_code=200)
    def delete_user(request: Request, body: DeleteUserRequest) -> dict[str, Any]:
        """Delete a user account (admin only)."""
        if not _is_authenticated(runtime, request.headers.get("x-session-token", "")):
            raise HTTPException(status_code=401, detail="Unauthorized")
        username = body.username.strip()

        sess = _session_info(runtime, request.headers.get("x-session-token", ""))
        current_user: str | None = sess.get("username") if sess else None
        if current_user == username:
            raise HTTPException(
                status_code=400, detail="Cannot delete your own account"
            )

        users: dict[str, Any] = runtime.web_settings.get("users") or {}
        if username not in users:
            raise HTTPException(status_code=404, detail="User not found")

        del users[username]
        runtime.web_settings["users"] = users

        # Invalidate all sessions for the deleted user
        sessions: dict[str, Any] = dict(runtime.web_settings.get("sessions") or {})
        for tok, sess in list(sessions.items()):
            if sess.get("username") == username:
                sessions.pop(tok, None)
        runtime.web_settings["sessions"] = sessions

        save_runtime_settings(runtime)
        return {"username": username, "deleted": True}

    @router.post("/change-password", status_code=200)
    def change_password(
        request: Request, body: ChangePasswordRequest
    ) -> dict[str, Any]:
        """Change own password (any authenticated user)."""
        if not _is_authenticated(runtime, request.headers.get("x-session-token", "")):
            raise HTTPException(status_code=401, detail="Unauthorized")

        sess = _session_info(runtime, request.headers.get("x-session-token", ""))
        current_user: str | None = sess.get("username") if sess else None
        if not current_user:
            raise HTTPException(status_code=401, detail="Unauthorized")

        users: dict[str, Any] = runtime.web_settings.get("users") or {}
        user_record = users.get(current_user)
        if not user_record:
            raise HTTPException(status_code=404, detail="User not found")

        if not _verify_password(user_record, body.old_password):
            raise HTTPException(status_code=403, detail="Current password is incorrect")

        import hashlib
        import secrets

        salt = secrets.token_hex(16)
        derived = hashlib.pbkdf2_hmac(
            "sha256", body.new_password.encode(), salt.encode(), 600_000
        )
        user_record["salt"] = salt
        user_record["hash"] = derived.hex()
        users[current_user] = user_record
        runtime.web_settings["users"] = users

        # Invalidate all other sessions for this user (keep current one)
        sessions: dict[str, Any] = dict(runtime.web_settings.get("sessions") or {})
        current_token = request.headers.get("x-session-token", "")
        for tok, sess in list(sessions.items()):
            if sess.get("username") == current_user and tok != current_token:
                sessions.pop(tok, None)
        runtime.web_settings["sessions"] = sessions

        save_runtime_settings(runtime)
        return {"username": current_user, "password_changed": True}

    return router
