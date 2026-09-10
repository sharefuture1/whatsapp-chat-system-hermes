from __future__ import annotations

from typing import Callable
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from whatsapp_chat_system.events.whatsapp import (
    EventProcessingError,
    WhatsAppEventEnvelope,
    WhatsAppEventService,
)
from whatsapp_chat_system.security.internal_auth import (
    DEFAULT_MAX_SKEW_SECONDS,
    InternalAuthError,
    InternalAuthHeaders,
    ReplayGuard,
    verify_internal_request,
)


def _request_id(request: Request) -> str:
    return (
        getattr(request.state, "request_id", None)
        or request.headers.get("X-Request-ID")
        or f"req_{uuid4().hex}"
    )


def error_response(
    request: Request,
    code: str,
    message: str,
    *,
    retryable: bool,
    status_code: int,
    details=None,
):
    request_id = _request_id(request)
    return JSONResponse(
        {
            "error": {
                "code": code,
                "message": message,
                "retryable": retryable,
                "request_id": request_id,
                "details": details or {},
            }
        },
        status_code=status_code,
        headers={"X-Request-ID": request_id},
    )


def internal_auth_exception_handler(request: Request, exc: InternalAuthError):
    """把鉴权失败翻译成与其它内部接口一致的结构化错误体。"""

    return error_response(
        request, exc.code, str(exc), retryable=False, status_code=exc.status_code
    )


def _make_internal_auth_dependency(
    *,
    internal_token: str,
    hmac_secret: str | None,
    max_skew_seconds: int,
    replay_guard: ReplayGuard | None,
) -> Callable[..., object]:
    """构造鉴权依赖。

    以依赖（而非在端点函数体内）实现，是因为 FastAPI 会先解析依赖、
    后解析请求体，这样鉴权在校验 payload 之前完成：未通过鉴权的请求
    不会进入 pydantic 校验路径。依赖体内 `await request.body()` 读取的是
    被 Starlette 缓存的原始字节，与签名口径一致。
    """

    async def dependency(
        request: Request,
        x_internal_token: str | None = Header(default=None),
        x_internal_timestamp: str | None = Header(default=None),
        x_internal_signature: str | None = Header(default=None),
        x_internal_nonce: str | None = Header(default=None),
    ) -> None:
        body = await request.body()
        verify_internal_request(
            configured_token=internal_token,
            headers=InternalAuthHeaders(
                token=x_internal_token,
                timestamp=x_internal_timestamp,
                signature=x_internal_signature,
                nonce=x_internal_nonce,
            ),
            body=body,
            hmac_secret=hmac_secret,
            max_skew_seconds=max_skew_seconds,
            replay_guard=replay_guard,
        )

    return dependency


def create_whatsapp_events_router(
    session_factory: Callable[[], Session],
    internal_token: str,
    *,
    hmac_secret: str | None = None,
    max_skew_seconds: int = DEFAULT_MAX_SKEW_SECONDS,
    replay_guard: ReplayGuard | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/internal/events", tags=["internal-events"])
    auth = _make_internal_auth_dependency(
        internal_token=internal_token,
        hmac_secret=hmac_secret,
        max_skew_seconds=max_skew_seconds,
        replay_guard=replay_guard,
    )

    @router.post("/whatsapp")
    def receive_whatsapp_event(
        request: Request,
        envelope: WhatsAppEventEnvelope,
        _auth: None = Depends(auth),
    ):
        session = session_factory()
        try:
            duplicate = WhatsAppEventService(session).process(envelope)
            session.commit()
        except (EventProcessingError, ValidationError) as exc:
            session.rollback()
            if isinstance(exc, EventProcessingError):
                return error_response(
                    request,
                    exc.code,
                    str(exc),
                    retryable=exc.retryable,
                    status_code=exc.status_code,
                )
            return error_response(
                request,
                "validation_error",
                "Invalid event payload",
                retryable=False,
                status_code=422,
                details={"errors": exc.errors()},
            )
        except IntegrityError:
            session.rollback()
            # 并发首次写竞争：重新读取身份并按普通 duplicate/conflict 规则判断。
            retry_session = session_factory()
            try:
                duplicate = WhatsAppEventService(retry_session).process(envelope)
                retry_session.commit()
            except EventProcessingError as exc:
                retry_session.rollback()
                return error_response(
                    request,
                    exc.code,
                    str(exc),
                    retryable=exc.retryable,
                    status_code=exc.status_code,
                )
            finally:
                retry_session.close()
        finally:
            session.close()

        return JSONResponse(
            {"accepted": True, "duplicate": duplicate, "event_id": envelope.event_id},
            headers={"X-Request-ID": _request_id(request)},
        )

    return router


def whatsapp_validation_exception_handler(
    request: Request, exc: RequestValidationError
):
    if request.url.path != "/internal/events/whatsapp":
        return None
    return error_response(
        request,
        "validation_error",
        "Invalid event envelope",
        retryable=False,
        status_code=422,
        details={"errors": exc.errors()},
    )
