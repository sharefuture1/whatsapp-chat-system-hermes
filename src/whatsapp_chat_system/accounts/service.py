from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from whatsapp_chat_system.db.models import WhatsAppAccount

from .repository import AccountRepository


class AccountError(Exception):
    code = 'account_error'


class AccountNotFoundError(AccountError):
    code = 'account_not_found'


class AccountConflictError(AccountError):
    code = 'account_name_conflict'


class AccountConfirmationError(AccountError):
    code = 'confirmation_mismatch'


class AccountValidationError(AccountError):
    code = 'validation_error'


class AccountService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = AccountRepository(session)

    @staticmethod
    def _clean_name(name: str) -> str:
        cleaned = name.strip()
        if not cleaned:
            raise AccountValidationError('name must not be empty')
        return cleaned

    def list(self) -> list[WhatsAppAccount]:
        return self.repository.list()

    def find(self, account_id: str) -> WhatsAppAccount | None:
        return self.repository.find(account_id)

    def get(self, account_id: str) -> WhatsAppAccount:
        account = self.find(account_id)
        if account is None:
            raise AccountNotFoundError(account_id)
        return account

    def create(
        self,
        *,
        name: str,
        is_primary: bool = False,
        ai_profile_id: str | None = None,
        auto_reply_mode: str = 'off',
    ) -> WhatsAppAccount:
        cleaned_name = self._clean_name(name)
        if self.repository.name_exists(cleaned_name):
            raise AccountConflictError(cleaned_name)
        if auto_reply_mode not in {'off', 'suggest', 'auto'}:
            raise AccountValidationError('invalid auto_reply_mode')

        account_id = str(uuid4())
        make_primary = self.repository.count() == 0 or is_primary
        if make_primary:
            self.repository.unset_primary()
        account = WhatsAppAccount(
            id=account_id,
            name=cleaned_name,
            session_ref=f'account:{account_id}',
            is_primary=make_primary,
            ai_profile_id=ai_profile_id,
            auto_reply_mode=auto_reply_mode,
        )
        self.repository.add(account)
        self.session.commit()
        return account

    def update(self, account_id: str, **changes: Any) -> WhatsAppAccount:
        account = self.get(account_id)
        if 'name' in changes:
            cleaned_name = self._clean_name(str(changes['name']))
            if self.repository.name_exists(cleaned_name, exclude_id=account_id):
                raise AccountConflictError(cleaned_name)
            account.name = cleaned_name
        if 'auto_reply_mode' in changes:
            mode = changes['auto_reply_mode']
            if mode not in {'off', 'suggest', 'auto'}:
                raise AccountValidationError('invalid auto_reply_mode')
            account.auto_reply_mode = mode
        for field in ('enabled', 'ai_profile_id'):
            if field in changes:
                setattr(account, field, changes[field])
        if changes.get('is_primary') is True:
            self.repository.unset_primary(exclude_id=account_id)
            account.is_primary = True
        self.session.commit()
        return account

    def update_status(self, account_id: str, status: str, **changes: Any) -> WhatsAppAccount:
        if status not in {'new', 'qr_pending', 'connecting', 'online', 'offline', 'error', 'logged_out'}:
            raise AccountValidationError('invalid status')
        account = self.get(account_id)
        account.status = status
        for field in ('phone_number', 'last_seen_at', 'last_error_code', 'last_error_message'):
            if field in changes:
                setattr(account, field, changes[field])
        self.session.commit()
        return account

    def delete(self, account_id: str, *, confirm_name: str) -> WhatsAppAccount:
        account = self.get(account_id)
        if confirm_name != account.name:
            raise AccountConfirmationError(account_id)
        was_primary = account.is_primary
        self.repository.delete(account)
        if was_primary:
            remaining = self.repository.list()
            if remaining:
                remaining[0].is_primary = True
        self.session.commit()
        return account

    @staticmethod
    def serialize(account: WhatsAppAccount) -> dict[str, Any]:
        def iso(value: datetime | None) -> str | None:
            return value.isoformat() if value else None

        return {
            'id': account.id,
            'name': account.name,
            'phone_number': account.phone_number,
            'status': account.status,
            'is_primary': account.is_primary,
            'enabled': account.enabled,
            'auto_reply_mode': account.auto_reply_mode,
            'ai_profile_id': account.ai_profile_id,
            'last_seen_at': iso(account.last_seen_at),
            'last_error_code': account.last_error_code,
            'last_error_message': account.last_error_message,
            'created_at': iso(account.created_at),
            'updated_at': iso(account.updated_at),
        }