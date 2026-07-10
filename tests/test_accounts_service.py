from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from whatsapp_chat_system.accounts.service import (
    AccountConflictError,
    AccountConfirmationError,
    AccountService,
)
from whatsapp_chat_system.db.base import Base


@pytest.fixture
def session() -> Session:
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        yield db
    engine.dispose()


def test_create_generates_uuid_controlled_session_ref_and_first_is_primary(session):
    service = AccountService(session)

    account = service.create(name='  Sales Laos  ', auto_reply_mode='suggest')
    public = service.serialize(account)

    UUID(account.id)
    assert account.name == 'Sales Laos'
    assert account.session_ref == f'account:{account.id}'
    assert account.is_primary is True
    assert account.status == 'new'
    assert 'hermes' not in account.session_ref.lower()
    assert 'session_ref' not in public


def test_setting_new_primary_atomically_unsets_old_primary(session):
    service = AccountService(session)
    first = service.create(name='A')
    second = service.create(name='B')

    service.update(second.id, is_primary=True)

    session.refresh(first)
    session.refresh(second)
    assert first.is_primary is False
    assert second.is_primary is True


def test_duplicate_names_are_rejected_case_insensitively(session):
    service = AccountService(session)
    service.create(name='Sales')

    with pytest.raises(AccountConflictError):
        service.create(name=' sales ')


def test_disable_preserves_session_and_other_account(session):
    service = AccountService(session)
    first = service.create(name='A')
    second = service.create(name='B')
    first_ref = first.session_ref

    service.update(first.id, enabled=False)

    assert service.get(first.id).enabled is False
    assert service.get(first.id).session_ref == first_ref
    assert service.get(second.id).enabled is True
    assert service.get(second.id).status == 'new'


def test_delete_requires_exact_confirmation_and_does_not_touch_other_account(session):
    service = AccountService(session)
    first = service.create(name='A')
    second = service.create(name='B')

    with pytest.raises(AccountConfirmationError):
        service.delete(first.id, confirm_name='wrong')

    deleted = service.delete(first.id, confirm_name='A')

    assert deleted.id == first.id
    assert service.find(first.id) is None
    assert service.get(second.id).name == 'B'
    assert service.get(second.id).is_primary is True
