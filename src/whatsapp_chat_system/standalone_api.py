"""Standalone API builder isolated from the legacy Hermes web application."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import inspect
from sqlalchemy.orm import Session, sessionmaker

from .accounts.reconciler import AccountReconciler
from .api.internal.whatsapp_events import (
    create_whatsapp_events_router,
    whatsapp_validation_exception_handler,
)
from .security.internal_auth import InternalAuthError, verify_internal_token
from .api.v1.accounts import BridgeProtocol, create_accounts_router
from .api.v1.conversations import create_conversations_router
from .api.v1.personas import create_personas_router
from .bridge.client import BridgeClient, BridgeError
from .db import Base, create_engine, create_session_factory
from .db import models as _models  # noqa: F401 -- registers every mapped table in Base.metadata
from .runtime import StandaloneRuntime, save_runtime_settings

logger = logging.getLogger(__name__)


class LoginRequest(BaseModel):
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


def _verify_password(record: dict[str, Any], password: str) -> bool:
    try:
        derived = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode(),
            str(record["salt"]).encode(),
            int(record["iterations"]),
        ).hex()
        return hmac.compare_digest(derived, str(record["hash"]))
    except (KeyError, TypeError, ValueError):
        return False


def _is_authenticated(runtime: StandaloneRuntime, request: Request) -> bool:
    token = request.headers.get("x-session-token", "")
    session = (runtime.web_settings.get("sessions") or {}).get(token)
    return bool(session and float(session.get("expires_at", 0)) > time.time())


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
) -> FastAPI:
    """Build a standalone API; schema migration is an external Alembic prerequisite."""
    runtime = StandaloneRuntime.from_env(
        runtime_dir, internal_event_token=internal_event_token
    )
    factory = account_session_factory or create_session_factory(create_engine())
    bridge = account_bridge or BridgeClient(
        base_url=os.getenv("WHATSAPP_BRIDGE_V2_URL", "http://127.0.0.1:3100"),
        internal_token=runtime.internal_event_token,
    )
    reconciler = AccountReconciler(factory, bridge)

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

        task = asyncio.create_task(reconcile_loop(), name="whatsapp-account-reconciler")
        app.state.account_reconciler_task = task
        try:
            yield
        finally:
            app.state.ready = False
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    app = FastAPI(title="WhatsApp Chat System API", version="0.5.2", lifespan=lifespan)
    app.state.runtime_mode = "standalone"
    app.state.ready = False
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(create_accounts_router(factory, bridge))
    app.include_router(create_conversations_router(factory, bridge))
    app.include_router(
        create_whatsapp_events_router(factory, runtime.internal_event_token)
    )
    app.include_router(create_personas_router(runtime, factory))

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
        if not _is_authenticated(runtime, request):
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
            }
        )

    @app.post("/api/login")
    def login(payload: LoginRequest) -> dict[str, Any]:
        if not _verify_password(
            runtime.web_settings.get("auth") or {}, payload.password
        ):
            raise HTTPException(status_code=401, detail="Invalid password")
        token = secrets.token_urlsafe(24)
        ttl = int(runtime.web_settings.get("auth_ttl_seconds") or 86400)
        sessions = dict(runtime.web_settings.get("sessions") or {})
        sessions[token] = {"issued_at": time.time(), "expires_at": time.time() + ttl}
        runtime.web_settings["sessions"] = sessions
        save_runtime_settings(runtime)
        return {"success": True, "session_token": token, "expires_in": ttl}

    @app.post("/api/logout")
    def logout(request: Request) -> dict[str, Any]:
        sessions = dict(runtime.web_settings.get("sessions") or {})
        sessions.pop(request.headers.get("x-session-token", ""), None)
        runtime.web_settings["sessions"] = sessions
        save_runtime_settings(runtime)
        return {"success": True}

    frontend_dist = _resolve_frontend_dist(web_dist)
    if frontend_dist:
        assets = frontend_dist / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            return FileResponse(frontend_dist / "index.html")

    return app
