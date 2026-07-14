from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any, Protocol
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from whatsapp_chat_system.accounts.service import (
    AccountConfirmationError,
    AccountError,
    AccountNotFoundError,
    AccountService,
    AccountValidationError,
)
from whatsapp_chat_system.bridge.client import BridgeError


class BridgeProtocol(Protocol):
    def create_account(self, account_id: str, session_ref: str) -> dict[str, Any]: ...

    def list_accounts(self) -> dict[str, Any]: ...

    def connect(self, account_id: str) -> dict[str, Any]: ...
    def qr(self, account_id: str) -> dict[str, Any]: ...
    def logout(self, account_id: str) -> dict[str, Any]: ...
    def stop(self, account_id: str) -> dict[str, Any]: ...
    def delete(
        self, account_id: str, *, delete_session: bool = False
    ) -> dict[str, Any]: ...
    def send(
        self,
        account_id: str,
        *,
        chat_id: str,
        text: str,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]: ...


class AccountCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    is_primary: bool = False
    ai_profile_id: str | None = None
    auto_reply_mode: str = "off"


class AccountUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    is_primary: bool | None = None
    enabled: bool | None = None
    ai_profile_id: str | None = None
    auto_reply_mode: str | None = None


class AccountDeleteRequest(BaseModel):
    confirm_name: str
    delete_session: bool = False


def create_accounts_router(
    session_factory: Callable[[], Session], bridge: BridgeProtocol
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/accounts", tags=["accounts"])

    def get_session() -> Generator[Session, None, None]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    def error_response(
        request: Request,
        code: str,
        message: str,
        *,
        status_code: int,
        retryable: bool = False,
    ) -> JSONResponse:
        request_id = request.headers.get("X-Request-ID") or f"req_{uuid4().hex}"
        return JSONResponse(
            {
                "error": {
                    "code": code,
                    "message": message,
                    "retryable": retryable,
                    "request_id": request_id,
                    "details": {},
                }
            },
            status_code=status_code,
            headers={"X-Request-ID": request_id},
        )

    def domain_error(request: Request, exc: AccountError) -> JSONResponse:
        status = 404 if isinstance(exc, AccountNotFoundError) else 409
        if isinstance(exc, AccountValidationError):
            status = 422
        return error_response(request, exc.code, str(exc), status_code=status)

    def bridge_error(request: Request, exc: BridgeError) -> JSONResponse:
        return error_response(
            request,
            exc.code,
            exc.message,
            status_code=exc.status_code,
            retryable=exc.retryable,
        )

    @router.get("")
    def list_accounts(session: Session = Depends(get_session)) -> dict[str, Any]:
        service = AccountService(session)
        items = [service.serialize(item) for item in service.list()]
        return {"items": items, "total": len(items)}

    @router.post("", status_code=201)
    def create_account(
        request: Request,
        payload: AccountCreateRequest,
        session: Session = Depends(get_session),
    ) -> Any:
        service = AccountService(session)
        account = None
        try:
            account = service.create(**payload.model_dump())
            bridge.create_account(account.id, account.session_ref)
            return service.serialize(account)
        except AccountError as exc:
            return domain_error(request, exc)
        except BridgeError as exc:
            # Bridge 注册失败时补偿删除刚创建的业务记录，避免孤儿账号阻塞重试。
            if account is not None:
                try:
                    service.delete(account.id, confirm_name=account.name)
                except AccountError:
                    pass
            return bridge_error(request, exc)

    @router.patch("/{account_id}")
    def update_account(
        account_id: str,
        request: Request,
        payload: AccountUpdateRequest,
        session: Session = Depends(get_session),
    ) -> Any:
        service = AccountService(session)
        changes = payload.model_dump(exclude_unset=True)
        if "name" in changes and changes["name"] is None:
            return error_response(
                request, "validation_error", "name must not be null", status_code=422
            )
        try:
            if changes.get("enabled") is False:
                # 先确认 Bridge 已停止，再提交业务停用状态，避免 socket 仍在线但 UI 显示停用。
                bridge.stop(account_id)
            account = service.update(account_id, **changes)
            return service.serialize(account)
        except AccountError as exc:
            return domain_error(request, exc)
        except BridgeError as exc:
            return bridge_error(request, exc)

    @router.post("/{account_id}/connect", status_code=202)
    def connect_account(
        account_id: str, request: Request, session: Session = Depends(get_session)
    ) -> Any:
        service = AccountService(session)
        try:
            account = service.get(account_id)
            bridge.connect(account_id)
            return {"accepted": True, "account": service.serialize(account)}
        except AccountError as exc:
            return domain_error(request, exc)
        except BridgeError as exc:
            return bridge_error(request, exc)

    @router.get("/{account_id}/qr")
    def account_qr(
        account_id: str, request: Request, session: Session = Depends(get_session)
    ) -> Any:
        service = AccountService(session)
        try:
            account = service.get(account_id)
            if account.status != "qr_pending":
                return error_response(
                    request,
                    "qr_not_pending",
                    "QR is only available while the account is qr_pending",
                    status_code=409,
                )
            return bridge.qr(account_id)
        except AccountError as exc:
            return domain_error(request, exc)
        except BridgeError as exc:
            return bridge_error(request, exc)

    @router.post("/{account_id}/logout")
    def logout_account(
        account_id: str, request: Request, session: Session = Depends(get_session)
    ) -> Any:
        service = AccountService(session)
        try:
            service.get(account_id)
            bridge.logout(account_id)
            account = service.update(account_id, enabled=False)
            account = service.update_status(account_id, "logged_out")
            return {"success": True, "account": service.serialize(account)}
        except AccountError as exc:
            return domain_error(request, exc)
        except BridgeError as exc:
            return bridge_error(request, exc)

    @router.delete("/{account_id}")
    def delete_account(
        account_id: str,
        request: Request,
        payload: AccountDeleteRequest,
        session: Session = Depends(get_session),
    ) -> Any:
        service = AccountService(session)
        try:
            account = service.get(account_id)
            if payload.confirm_name != account.name:
                raise AccountConfirmationError(account_id)
            bridge.delete(account_id, delete_session=payload.delete_session)
            service.delete(account_id, confirm_name=payload.confirm_name)
            return {
                "success": True,
                "deleted": account_id,
                "session_deleted": payload.delete_session,
            }
        except AccountError as exc:
            return domain_error(request, exc)
        except BridgeError as exc:
            return bridge_error(request, exc)

    return router
