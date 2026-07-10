from __future__ import annotations

from typing import Callable
from uuid import uuid4

from fastapi import APIRouter, Header, Request
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
from whatsapp_chat_system.security.internal_auth import InternalAuthError, verify_internal_token


def _request_id(request: Request) -> str:
    return getattr(request.state, 'request_id', None) or request.headers.get('X-Request-ID') or f'req_{uuid4().hex}'


def error_response(request: Request, code: str, message: str, *, retryable: bool, status_code: int, details=None):
    request_id = _request_id(request)
    return JSONResponse(
        {
            'error': {
                'code': code,
                'message': message,
                'retryable': retryable,
                'request_id': request_id,
                'details': details or {},
            }
        },
        status_code=status_code,
        headers={'X-Request-ID': request_id},
    )


def create_whatsapp_events_router(
    session_factory: Callable[[], Session], internal_token: str
) -> APIRouter:
    router = APIRouter(prefix='/internal/events', tags=['internal-events'])

    @router.post('/whatsapp')
    def receive_whatsapp_event(
        request: Request,
        envelope: WhatsAppEventEnvelope,
        x_internal_token: str | None = Header(default=None),
    ):
        try:
            verify_internal_token(internal_token, x_internal_token)
        except InternalAuthError as exc:
            return error_response(
                request, exc.code, str(exc), retryable=False, status_code=exc.status_code
            )

        session = session_factory()
        try:
            duplicate = WhatsAppEventService(session).process(envelope)
            session.commit()
        except (EventProcessingError, ValidationError) as exc:
            session.rollback()
            if isinstance(exc, EventProcessingError):
                return error_response(
                    request, exc.code, str(exc), retryable=exc.retryable,
                    status_code=exc.status_code,
                )
            return error_response(
                request, 'validation_error', 'Invalid event payload', retryable=False,
                status_code=422, details={'errors': exc.errors()},
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
                    request, exc.code, str(exc), retryable=exc.retryable,
                    status_code=exc.status_code,
                )
            finally:
                retry_session.close()
        finally:
            session.close()

        return JSONResponse(
            {'accepted': True, 'duplicate': duplicate, 'event_id': envelope.event_id},
            headers={'X-Request-ID': _request_id(request)},
        )

    return router


def whatsapp_validation_exception_handler(request: Request, exc: RequestValidationError):
    if request.url.path != '/internal/events/whatsapp':
        return None
    return error_response(
        request, 'validation_error', 'Invalid event envelope', retryable=False,
        status_code=422, details={'errors': exc.errors()},
    )
