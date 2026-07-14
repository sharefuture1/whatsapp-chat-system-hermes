"""Standalone API builder isolated from the legacy Hermes web application."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from threading import RLock
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import inspect
from sqlalchemy.orm import Session, sessionmaker

from .accounts.reconciler import AccountReconciler
from .api.internal.whatsapp_events import (
    create_whatsapp_events_router,
    whatsapp_validation_exception_handler,
)
from .api.v1.accounts import BridgeProtocol, create_accounts_router
from .api.v1.conversations import create_conversations_router
from .api.v1.personas import create_personas_router
from .api.v1.operations import create_operations_router
from .api.v1.settings import create_settings_router
from .bridge.client import BridgeClient, BridgeError
from .db import Base, create_engine, create_session_factory
from .db import models as _models  # noqa: F401 -- registers every mapped table in Base.metadata
from .outbox import OutboxDispatcher
from .runtime import (
    StandaloneRuntime,
    is_authenticated as _is_authenticated,
    verify_password as _verify_password,
    save_runtime_settings,
)
from .security.internal_auth import InternalAuthError, verify_internal_token

logger = logging.getLogger(__name__)

_DEFAULT_ALLOWED_ORIGINS = (
    "https://whats.future1.us",
    "http://127.0.0.1:38998",
    "http://localhost:38998",
)


class LoginRequest(BaseModel):
    username: str = Field(default="", max_length=128)
    password: str


class DisabledBridgeClient:
    @staticmethod
    def _disabled(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise BridgeError(
            "bridge_not_configured",
            "WhatsApp Bridge V2 is not configured",
            retryable=False,
            status_code=503,
        )

    create_account = _disabled
    list_accounts = _disabled
    connect = _disabled
    qr = _disabled
    logout = _disabled
    stop = _disabled
    delete = _disabled
    send = _disabled


def _allowed_cors_origins(raw: str | None = None) -> list[str]:
    """Return a deterministic, explicit browser origin allowlist.

    Wildcard origins are deliberately rejected because the web console carries an
    operator session token. Additional production origins can be supplied as a
    comma-separated CHAT_SYSTEM_ALLOWED_ORIGINS value.
    """

    configured = (
        os.getenv("CHAT_SYSTEM_ALLOWED_ORIGINS", "") if raw is None else raw
    ).strip()
    candidates = configured.split(",") if configured else list(_DEFAULT_ALLOWED_ORIGINS)
    origins: list[str] = []
    for candidate in candidates:
        origin = candidate.strip().rstrip("/")
        if not origin or origin == "*":
            continue
        if not origin.startswith(("https://", "http://")):
            continue
        if origin not in origins:
            origins.append(origin)
    if not origins:
        return list(_DEFAULT_ALLOWED_ORIGINS)
    return origins


def _positive_policy_int(value: Any, default: int, *, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if 1 <= parsed <= maximum else default


def _login_policy(runtime: StandaloneRuntime) -> tuple[int, int]:
    policy = runtime.web_settings.get("auth_policy") or {}
    return (
        _positive_policy_int(policy.get("max_attempts"), 5, maximum=100),
        _positive_policy_int(policy.get("window_seconds"), 300, maximum=86400),
    )


def _recent_login_attempts(
    values: Any,
    *,
    now: float,
    window_seconds: int,
) -> list[float]:
    if not isinstance(values, list):
        return []
    recent: list[float] = []
    for value in values:
        try:
            timestamp = float(value)
        except (TypeError, ValueError):
            continue
        if 0 <= now - timestamp < window_seconds:
            recent.append(timestamp)
    return recent


def _current_alembic_head() -> str:
    project_root = Path(__file__).resolve().parents[2]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "migrations"))
    head = ScriptDirectory.from_config(config).get_current_head()
    if head is None:
        raise RuntimeError("standalone migration scripts have no single head revision")
    return head


def _schema_ready(factory: sessionmaker[Session]) -> bool:
    bind = factory.kw.get("bind")
    if bind is None:
        return False
    try:
        inspector = inspect(bind)
        actual = set(inspector.get_table_names())
        if (
            not set(Base.metadata.tables).issubset(actual)
            or "alembic_version" not in actual
        ):
            return False
        with bind.connect() as connection:
            revisions = [
                str(row[0])
                for row in connection.exec_driver_sql(
                    "SELECT version_num FROM alembic_version"
                )
            ]
        return revisions == [_current_alembic_head()]
    except Exception:
        logger.exception("Standalone schema readiness check failed")
        return False


def _resolve_frontend_dist(web_dist: str | Path | None) -> Path | None:
    if web_dist is None:
        return None
    path = Path(web_dist)
    return path if (path / "index.html").is_file() else None


def build_standalone_app(
    *,
    web_dist: str | Path | None = None,
    runtime_dir: str | Path | None = None,
    account_session_factory: sessionmaker[Session] | None = None,
    account_bridge: BridgeProtocol | None = None,
    internal_event_token: str | None = None,
    account_reconcile_interval_seconds: float = 45.0,
    outbox_poll_interval_seconds: float = 1.0,
) -> FastAPI:
    """Build a standalone API; schema migration is an external Alembic prerequisite."""
    runtime = StandaloneRuntime.from_env(
        runtime_dir, internal_event_token=internal_event_token
    )
    factory = account_session_factory or create_session_factory(create_engine())

    # Set up AI runtime settings so Rewriter can find the WendingAI API key
    from whatsapp_chat_system.web_api import setup_ai_runtime_settings

    setup_ai_runtime_settings(runtime.ai_settings)
    bridge = account_bridge or BridgeClient(
        base_url=os.getenv("WHATSAPP_BRIDGE_V2_URL", "http://127.0.0.1:3100"),
        internal_token=runtime.internal_event_token,
    )
    reconciler = AccountReconciler(factory, bridge)
    outbox_dispatcher = OutboxDispatcher(factory, bridge)
    login_lock = RLock()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if not _schema_ready(factory):
            app.state.ready = False
            raise RuntimeError(
                "standalone database schema is not ready; run 'alembic upgrade head' before starting"
            )
        app.state.ready = True

        async def reconcile_loop() -> None:
            while True:
                try:
                    await asyncio.to_thread(reconciler.reconcile_once)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("WhatsApp account reconciliation round failed")
                await asyncio.sleep(account_reconcile_interval_seconds)

        async def outbox_loop() -> None:
            while True:
                try:
                    processed = await asyncio.to_thread(outbox_dispatcher.run_once)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Outbound message worker round failed")
                    processed = 0
                await asyncio.sleep(0 if processed else outbox_poll_interval_seconds)

        reconcile_task = asyncio.create_task(
            reconcile_loop(), name="whatsapp-account-reconciler"
        )
        outbox_task = asyncio.create_task(outbox_loop(), name="whatsapp-outbox-worker")
        app.state.account_reconciler_task = reconcile_task
        app.state.outbox_worker_task = outbox_task
        try:
            yield
        finally:
            app.state.ready = False
            reconcile_task.cancel()
            outbox_task.cancel()
            await asyncio.gather(reconcile_task, outbox_task, return_exceptions=True)

    app = FastAPI(title="WhatsApp Chat System API", version="0.6.0", lifespan=lifespan)
    app.state.runtime_mode = "standalone"
    app.state.ready = False
    app.state.runtime = runtime
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_cors_origins(),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Content-Type",
            "X-Session-Token",
            "X-Request-ID",
            "Idempotency-Key",
        ],
        expose_headers=["X-Request-ID"],
        max_age=600,
    )
    app.include_router(create_accounts_router(factory, bridge))
    app.include_router(create_conversations_router(factory, bridge))
    app.include_router(
        create_whatsapp_events_router(factory, runtime.internal_event_token)
    )
    app.include_router(create_personas_router(runtime, factory))
    # Lazy import to avoid circular dependency at module load time
    from .api.v1.users import create_users_router as _create_users_router
    from .api.v1.messages import create_messages_router as _create_messages_router

    app.include_router(create_settings_router(runtime, factory))
    app.include_router(create_operations_router(factory))
    app.include_router(_create_users_router(runtime))
    app.include_router(_create_messages_router())

    @app.middleware("http")
    async def auth_guard(request: Request, call_next):
        path = request.url.path
        if path == "/internal/events/whatsapp":
            try:
                # Authenticate before FastAPI parses the event body, so an
                # unauthenticated malformed payload cannot probe its schema.
                verify_internal_token(
                    runtime.internal_event_token,
                    request.headers.get("X-Internal-Token"),
                )
            except InternalAuthError as exc:
                return JSONResponse(
                    {
                        "error": {
                            "code": exc.code,
                            "message": str(exc),
                            "retryable": False,
                            "details": {},
                        }
                    },
                    status_code=exc.status_code,
                )
        if path == "/api" or (
            path.startswith("/api/")
            and not path.startswith("/api/v1/")
            and path not in {"/api/health", "/api/login", "/api/logout"}
        ):
            return JSONResponse({"code": "legacy_api_disabled"}, status_code=410)
        if (
            request.method == "OPTIONS"
            or not path.startswith("/api")
            or path in {"/api/health", "/api/login", "/api/logout"}
        ):
            return await call_next(request)
        if not _is_authenticated(runtime, request.headers.get("x-session-token", "")):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        return await call_next(request)

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request.state.request_id = (
            request.headers.get("X-Request-ID") or f"req_{secrets.token_hex(16)}"
        )
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(RequestValidationError)
    async def standalone_validation_exception_handler(
        request: Request, exc: RequestValidationError
    ):
        response = whatsapp_validation_exception_handler(request, exc)
        if response is not None:
            return response
        return await request_validation_exception_handler(request, exc)

    @app.get("/api/health")
    def health() -> JSONResponse:
        if not app.state.ready:
            return JSONResponse(
                {"ok": False, "runtime_mode": "standalone"}, status_code=503
            )
        return JSONResponse(
            {
                "ok": True,
                "runtime_mode": "standalone",
                "ts": time.time(),
                "login_enabled": True,
                "outbox_worker": "running",
            }
        )

    @app.post("/api/login")
    def login(request: Request, payload: LoginRequest) -> dict[str, Any]:
        client_ip = (request.client.host if request.client else "unknown") or "unknown"
        now = time.time()
        max_attempts, window_seconds = _login_policy(runtime)
        with login_lock:
            attempt_map = dict(runtime.web_settings.get("login_attempts") or {})
            recent = _recent_login_attempts(
                attempt_map.get(client_ip),
                now=now,
                window_seconds=window_seconds,
            )
            if len(recent) >= max_attempts:
                attempt_map[client_ip] = recent
                runtime.web_settings["login_attempts"] = attempt_map
                save_runtime_settings(runtime)
                raise HTTPException(
                    status_code=429,
                    detail={
                        "code": "login_rate_limited",
                        "message": "Too many login attempts, try again later",
                    },
                )

            # Multi-user lookup: username → password record
            users: dict[str, Any] = runtime.web_settings.get("users") or {}
            username = (payload.username or "").strip()
            if not username:
                recent.append(now)
                attempt_map[client_ip] = recent
                runtime.web_settings["login_attempts"] = attempt_map
                save_runtime_settings(runtime)
                raise HTTPException(status_code=401, detail="Username is required")

            # ── Migration: auth (old single-password) → users (new multi-user) ──
            # If no users exist yet, bootstrap from the legacy auth record.
            # This is a one-time migration on the first login after upgrade.
            if not users and runtime.web_settings.get("auth"):
                admin_pw = "Welcome2026!"  # temp password – forces change on next login
                salt = secrets.token_hex(16)
                derived = hashlib.pbkdf2_hmac(
                    "sha256", admin_pw.encode(), salt.encode(), 600_000
                )
                users["admin"] = {
                    "scheme": "pbkdf2_sha256",
                    "salt": salt,
                    "iterations": 600_000,
                    "hash": derived.hex(),
                    "created_at": time.time(),
                    "password_change_required": True,
                }
                runtime.web_settings["users"] = users
                # Keep legacy auth for backward compat during migration window
                save_runtime_settings(runtime)

            user_record: dict[str, Any] | None = users.get(username)
            # Backward compat: also accept legacy auth (single shared password)
            if not user_record and username == "admin":
                user_record = runtime.web_settings.get("auth")
            if not user_record or not _verify_password(user_record, payload.password):
                recent.append(now)
                attempt_map[client_ip] = recent
                runtime.web_settings["login_attempts"] = attempt_map
                save_runtime_settings(runtime)
                raise HTTPException(
                    status_code=401, detail="Invalid username or password"
                )

            # If password_change_required, return flag so frontend forces a change
            needs_password_change = False
            if user_record.get("password_change_required"):
                needs_password_change = True
                # Clear the flag on successful login so they land in the app
                user_record.pop("password_change_required", None)
                users[username] = user_record
                runtime.web_settings["users"] = users
                save_runtime_settings(runtime)

            # Logout all existing sessions for this user (single-session policy)
            sessions = dict(runtime.web_settings.get("sessions") or {})
            for tok, sess in list(sessions.items()):
                if (
                    sess.get("username") == username
                    and float(sess.get("expires_at", 0)) > now
                ):
                    sessions.pop(tok, None)

            attempt_map.pop(client_ip, None)
            runtime.web_settings["login_attempts"] = attempt_map
            token = secrets.token_urlsafe(24)
            ttl = int(runtime.web_settings.get("auth_ttl_seconds") or 86400)
            sessions[token] = {
                "issued_at": now,
                "expires_at": now + ttl,
                "username": username,
            }
            runtime.web_settings["sessions"] = sessions
            save_runtime_settings(runtime)

        resp: dict[str, Any] = {
            "success": True,
            "session_token": token,
            "expires_in": ttl,
            "username": username,
        }
        if needs_password_change:
            resp["password_change_required"] = True
        return resp

    @app.post("/api/logout")
    def logout(request: Request) -> dict[str, Any]:
        with login_lock:
            sessions = dict(runtime.web_settings.get("sessions") or {})
            sessions.pop(request.headers.get("x-session-token", ""), None)
            runtime.web_settings["sessions"] = sessions
            save_runtime_settings(runtime)
        return {"success": True}

    frontend_dist = _resolve_frontend_dist(web_dist)
    if frontend_dist:
        assets = frontend_dist / "assets"
        if assets.is_dir():
            # Mount immutable-asset mount with aggressive cache + etag;
            # /index.html is served via the catch-all SPA route below (no-cache).
            app.mount(
                "/assets",
                _CacheControlledStaticFiles(directory=assets),
                name="assets",
            )

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            return FileResponse(frontend_dist / "index.html")

    return app


class _CacheControlledStaticFiles(StaticFiles):
    """StaticFiles that adds Cache-Control: public, max-age=31536000, immutable
    and Last-Modified to every served file (matching Vite immutable hashes)."""

    def file_response(self, name: str, *args, **kwargs) -> Response:  # type: ignore[override]
        resp = super().file_response(name, *args, **kwargs)
        if resp.status_code == 200:
            resp.headers.setdefault(
                "Cache-Control", "public, max-age=31536000, immutable"
            )
            resp.headers.setdefault("Last-Modified", "Thu, 01 Jan 1970 00:00:00 GMT")
        return resp
