from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from whatsapp_chat_system.db.models import WhatsAppAccount


class AccountRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list(self) -> list[WhatsAppAccount]:
        statement = select(WhatsAppAccount).order_by(
            WhatsAppAccount.is_primary.desc(), WhatsAppAccount.created_at, WhatsAppAccount.id
        )
        return list(self.session.scalars(statement))

    def find(self, account_id: str) -> WhatsAppAccount | None:
        return self.session.get(WhatsAppAccount, account_id)

    def count(self) -> int:
        return int(self.session.scalar(select(func.count()).select_from(WhatsAppAccount)) or 0)

    def name_exists(self, name: str, *, exclude_id: str | None = None) -> bool:
        statement = select(WhatsAppAccount.id).where(func.lower(WhatsAppAccount.name) == name.lower())
        if exclude_id is not None:
            statement = statement.where(WhatsAppAccount.id != exclude_id)
        return self.session.scalar(statement.limit(1)) is not None

    def add(self, account: WhatsAppAccount) -> WhatsAppAccount:
        self.session.add(account)
        self.session.flush()
        return account

    def unset_primary(self, *, exclude_id: str | None = None) -> None:
        statement = update(WhatsAppAccount).where(WhatsAppAccount.is_primary.is_(True))
        if exclude_id is not None:
            statement = statement.where(WhatsAppAccount.id != exclude_id)
        self.session.execute(statement.values(is_primary=False))

    def delete(self, account: WhatsAppAccount) -> None:
        self.session.delete(account)
        self.session.flush()