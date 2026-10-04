"""Outbox-backed standalone scheduling, broadcast, and queue diagnostics APIs."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Generator
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from whatsapp_chat_system.authz import (
    require_admin,
    require_operator,
    visible_account_ids_for,
)
from whatsapp_chat_system.db.models import Conversation, Message, OutboxMessage
from whatsapp_chat_system.outbox import enqueue_outbox_message
from whatsapp_chat_system.runtime import StandaloneRuntime


class ScheduleRequest(BaseModel):
    target: str = Field(min_length=1, max_length=255)
    message: str = Field(min_length=1, max_length=10000)
    run_at: float
    account_id: str | None = None
    idempotency_key: str | None = Field(default=None, max_length=255)
    mode: str = "direct"
    use_memory: bool = True


class BroadcastRequest(BaseModel):
    targets: list[str] = Field(min_length=1, max_length=500)
    message: str = Field(min_length=1, max_length=10000)
    account_id: str | None = None
    idempotency_key: str | None = Field(default=None, max_length=128)
    mode: str = "direct"
    use_memory: bool = True


def _resolve_conversation(
    session: Session,
    target: str,
    account_id: str | None,
    visible_account_ids: list[str] | None,
) -> Conversation:
    if (
        account_id
        and visible_account_ids is not None
        and account_id not in visible_account_ids
    ):
        raise HTTPException(status_code=403, detail="Account not allowed")

    cleaned = target.strip()
    direct = session.get(Conversation, cleaned)
    if direct is not None and direct.deleted_at is None:
        if account_id and direct.account_id != account_id:
            raise HTTPException(
                status_code=404, detail="Conversation not found in account"
            )
        if (
            visible_account_ids is not None
            and direct.account_id not in visible_account_ids
        ):
            raise HTTPException(status_code=404, detail="Conversation not found")
        return direct

    statement = select(Conversation).where(
        Conversation.remote_jid == cleaned,
        Conversation.deleted_at.is_(None),
        Conversation.archived.is_(False),
    )
    if account_id:
        statement = statement.where(Conversation.account_id == account_id)
    if visible_account_ids is not None:
        statement = statement.where(Conversation.account_id.in_(visible_account_ids))
    rows = session.scalars(statement.order_by(Conversation.id.asc()).limit(2)).all()
    if not rows:
        raise HTTPException(
            status_code=404, detail=f"Conversation not found: {cleaned}"
        )
    if len(rows) > 1:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ambiguous_target",
                "message": "Target exists in multiple accounts; provide account_id",
                "target": cleaned,
            },
        )
    return rows[0]


def _schedule_payload(
    outbox: OutboxMessage,
    message: Message,
    conversation: Conversation,
) -> dict[str, Any]:
    return {
        "id": outbox.id,
        "target": conversation.remote_jid,
        "account_id": conversation.account_id,
        "conversation_id": conversation.id,
        "message": message.content or "",
        "run_at": outbox.available_at.timestamp(),
        "status": outbox.status,
        "attempts": outbox.attempts,
        "last_error": outbox.last_error,
    }


def _require_broadcast_enabled(runtime: StandaloneRuntime, request: Request) -> None:
    require_admin(runtime, request)
    enabled = bool((runtime.web_settings.get("plugins") or {}).get("broadcast", False))
    if not enabled:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "broadcast_disabled",
                "message": "Mass broadcast is disabled until explicitly enabled by deployment configuration",
            },
        )


def create_operations_router(
    runtime: StandaloneRuntime,
    session_factory: Callable[[], Session],
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["operations"])

    def get_session() -> Generator[Session, None, None]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    @router.get("/schedule")
    def list_schedule(
        request: Request,
        limit: int = Query(default=100, ge=1, le=500),
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        visible_ids = visible_account_ids_for(runtime, request)
        statement = (
            select(OutboxMessage, Message, Conversation)
            .join(Message, Message.id == OutboxMessage.message_id)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(OutboxMessage.idempotency_key.like("schedule:%"))
            .order_by(OutboxMessage.available_at.asc(), OutboxMessage.id.asc())
            .limit(limit)
        )
        if visible_ids is not None:
            statement = statement.where(OutboxMessage.account_id.in_(visible_ids))
        rows = session.execute(statement).all()
        items = [
            _schedule_payload(outbox, message, conversation)
            for outbox, message, conversation in rows
        ]
        return {"items": items, "total": len(items)}

    @router.post("/schedule", status_code=202)
    def create_schedule(
        request: Request,
        payload: ScheduleRequest,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        require_operator(runtime, request)
        visible_ids = visible_account_ids_for(runtime, request)
        now = datetime.now(timezone.utc)
        run_at = datetime.fromtimestamp(payload.run_at, tz=timezone.utc)
        if run_at <= now:
            raise HTTPException(status_code=422, detail="run_at must be in the future")
        if run_at.year > now.year + 5:
            raise HTTPException(
                status_code=422, detail="run_at is too far in the future"
            )
        conversation = _resolve_conversation(
            session, payload.target, payload.account_id, visible_ids
        )
        key = payload.idempotency_key or f"schedule:{uuid4()}"
        if not key.startswith("schedule:"):
            key = f"schedule:{key}"
        if len(key) > 255:
            raise HTTPException(
                status_code=422,
                detail="idempotency_key exceeds 255 characters after schedule prefix",
            )
        message, outbox, created = enqueue_outbox_message(
            session,
            conversation,
            text=payload.message,
            available_at=run_at,
            idempotency_key=key,
        )
        session.commit()
        return {
            "success": True,
            "created": created,
            **_schedule_payload(outbox, message, conversation),
        }

    @router.delete("/schedule/{outbox_id}")
    def cancel_schedule(
        request: Request,
        outbox_id: str,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        require_operator(runtime, request)
        visible_ids = visible_account_ids_for(runtime, request)
        statement = select(OutboxMessage).where(OutboxMessage.id == outbox_id)
        if visible_ids is not None:
            statement = statement.where(OutboxMessage.account_id.in_(visible_ids))
        outbox = session.scalar(statement)
        if outbox is None or not outbox.idempotency_key.startswith("schedule:"):
            raise HTTPException(status_code=404, detail="Scheduled message not found")
        if outbox.status == "completed":
            raise HTTPException(
                status_code=409, detail="Scheduled message was already sent"
            )
        message = session.get(Message, outbox.message_id)
        outbox.status = "dead"
        outbox.last_error = "schedule_cancelled"
        outbox.lease_owner = None
        outbox.lease_expires_at = None
        if message is not None:
            message.status = "failed"
            message.error_code = "schedule_cancelled"
            message.error_message = "Scheduled message was cancelled"
        session.commit()
        return {"success": True, "id": outbox.id, "status": outbox.status}

    @router.get("/broadcast")
    def list_broadcasts(
        request: Request,
        limit: int = Query(default=50, ge=1, le=200),
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        _require_broadcast_enabled(runtime, request)
        rows = session.execute(
            select(OutboxMessage, Message, Conversation)
            .join(Message, Message.id == OutboxMessage.message_id)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(OutboxMessage.idempotency_key.like("broadcast:%"))
            .order_by(OutboxMessage.created_at.desc())
            .limit(limit * 500)
        ).all()
        grouped: dict[str, list[tuple[OutboxMessage, Message, Conversation]]] = (
            defaultdict(list)
        )
        for row in rows:
            key = row[0].idempotency_key.split(":", 2)
            batch_id = key[1] if len(key) > 1 else row[0].id
            grouped[batch_id].append(row)
        items = []
        for batch_id, batch_rows in grouped.items():
            first = batch_rows[0]
            items.append(
                {
                    "id": batch_id,
                    "created_at": first[0].created_at.timestamp(),
                    "message": first[1].content or "",
                    "targets": [row[2].remote_jid for row in batch_rows],
                    "results": [
                        {
                            "target": row[2].remote_jid,
                            "account_id": row[2].account_id,
                            "success": row[0].status == "completed",
                            "status": row[0].status,
                            "error": row[0].last_error,
                        }
                        for row in batch_rows
                    ],
                }
            )
        items.sort(key=lambda item: item["created_at"], reverse=True)
        return {"items": items[:limit], "total": len(items)}

    @router.post("/broadcast", status_code=202)
    def create_broadcast(
        request: Request,
        payload: BroadcastRequest,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        _require_broadcast_enabled(runtime, request)
        visible_ids = visible_account_ids_for(runtime, request)
        targets = list(
            dict.fromkeys(
                target.strip() for target in payload.targets if target.strip()
            )
        )
        if not targets:
            raise HTTPException(status_code=422, detail="targets must not be empty")
        batch_id = payload.idempotency_key or uuid4().hex
        queued: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        for target in targets:
            try:
                conversation = _resolve_conversation(
                    session, target, payload.account_id, visible_ids
                )
                message, outbox, created = enqueue_outbox_message(
                    session,
                    conversation,
                    text=payload.message,
                    idempotency_key=f"broadcast:{batch_id}:{conversation.id}",
                )
                queued.append(
                    {
                        "target": conversation.remote_jid,
                        "account_id": conversation.account_id,
                        "conversation_id": conversation.id,
                        "local_message_id": message.id,
                        "outbox_id": outbox.id,
                        "created": created,
                    }
                )
            except HTTPException as exc:
                rejected.append({"target": target, "detail": exc.detail})
        if not queued:
            session.rollback()
            raise HTTPException(
                status_code=422,
                detail={"code": "broadcast_no_valid_targets", "rejected": rejected},
            )
        session.commit()
        return {
            "success": True,
            "id": batch_id,
            "queued": queued,
            "rejected": rejected,
            "queued_count": len(queued),
            "rejected_count": len(rejected),
        }

    @router.get("/outbox")
    def outbox_status(
        request: Request,
        limit: int = Query(default=100, ge=1, le=500),
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        require_operator(runtime, request)
        visible_ids = visible_account_ids_for(runtime, request)
        statement = (
            select(OutboxMessage, Message)
            .join(Message, Message.id == OutboxMessage.message_id)
            .order_by(OutboxMessage.created_at.desc())
            .limit(limit)
        )
        if visible_ids is not None:
            statement = statement.where(OutboxMessage.account_id.in_(visible_ids))
        rows = session.execute(statement).all()
        return {
            "items": [
                {
                    "id": outbox.id,
                    "message_id": message.id,
                    "account_id": outbox.account_id,
                    "conversation_id": message.conversation_id,
                    "status": outbox.status,
                    "attempts": outbox.attempts,
                    "available_at": outbox.available_at.isoformat(),
                    "last_error": outbox.last_error,
                }
                for outbox, message in rows
            ],
            "total": len(rows),
        }

    return router
