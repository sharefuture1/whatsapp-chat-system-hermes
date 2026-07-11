from __future__ import annotations

import logging
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from whatsapp_chat_system.db.models import WhatsAppAccount

logger = logging.getLogger(__name__)


class ReconciliationBridge(Protocol):
    def list_accounts(self) -> dict[str, Any]: ...
    def create_account(self, account_id: str, session_ref: str) -> dict[str, Any]: ...
    def connect(self, account_id: str) -> dict[str, Any]: ...


class AccountReconciler:
    def __init__(self, session_factory: sessionmaker[Session], bridge: ReconciliationBridge) -> None:
        self.session_factory = session_factory
        self.bridge = bridge

    def reconcile_once(self) -> dict[str, int]:
        payload = self.bridge.list_accounts()
        items = payload.get('items') if isinstance(payload, dict) else []
        bridge_states = {
            str(item.get('account_id')): str(item.get('state'))
            for item in items or []
            if isinstance(item, dict) and item.get('account_id')
        }
        with self.session_factory() as session:
            accounts = list(session.scalars(select(WhatsAppAccount).where(
                WhatsAppAccount.enabled.is_(True),
                WhatsAppAccount.status != 'logged_out',
            )))

        result = {'examined': len(accounts), 'created': 0, 'connected': 0, 'failed': 0}
        for account in accounts:
            try:
                state = bridge_states.get(account.id)
                if state is None:
                    self.bridge.create_account(account.id, account.session_ref)
                    result['created'] += 1
                    state = 'new'
                if state not in {'online', 'connecting', 'qr_pending'}:
                    self.bridge.connect(account.id)
                    result['connected'] += 1
            except Exception:
                result['failed'] += 1
                logger.exception(
                    'WhatsApp account reconciliation failed',
                    extra={'account_id': account.id},
                )
        return result
