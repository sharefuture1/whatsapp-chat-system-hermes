from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from whatsapp_chat_system.accounts.reconciler import AccountReconciler
from whatsapp_chat_system.db.base import Base
from whatsapp_chat_system.db.models import WhatsAppAccount


class FakeBridge:
    def __init__(self, statuses=None, failures=None):
        self.statuses = statuses or []
        self.failures = failures or {}
        self.calls = []

    def list_accounts(self):
        self.calls.append(('list',))
        return {'items': self.statuses, 'total': len(self.statuses)}

    def create_account(self, account_id, session_ref):
        self.calls.append(('create', account_id, session_ref))
        if self.failures.get(account_id) == 'create':
            raise RuntimeError('create failed')

    def connect(self, account_id):
        self.calls.append(('connect', account_id))
        if self.failures.get(account_id) == 'connect':
            raise RuntimeError('connect failed')


def factory_with(*accounts):
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    with factory() as session:
        session.add_all(accounts)
        session.commit()
    return factory


def account(account_id, *, enabled=True, status='offline'):
    return WhatsAppAccount(
        id=account_id, name=account_id, session_ref=f'account:{account_id}',
        enabled=enabled, status=status,
    )


def test_reconcile_registers_missing_enabled_account_then_connects():
    bridge = FakeBridge()
    reconciler = AccountReconciler(factory_with(account('A')), bridge)

    result = reconciler.reconcile_once()

    assert bridge.calls == [('list',), ('create', 'A', 'account:A'), ('connect', 'A')]
    assert result == {'examined': 1, 'created': 1, 'connected': 1, 'failed': 0}


def test_reconcile_is_idempotent_for_online_and_skips_disabled_or_logged_out():
    bridge = FakeBridge(statuses=[{'account_id': 'A', 'state': 'online'}])
    reconciler = AccountReconciler(factory_with(
        account('A'), account('B', enabled=False), account('C', status='logged_out'),
    ), bridge)

    result = reconciler.reconcile_once()

    assert bridge.calls == [('list',)]
    assert result == {'examined': 1, 'created': 0, 'connected': 0, 'failed': 0}


def test_reconcile_one_account_failure_does_not_block_other_accounts():
    bridge = FakeBridge(failures={'A': 'create'})
    reconciler = AccountReconciler(factory_with(account('A'), account('B')), bridge)

    result = reconciler.reconcile_once()

    assert ('connect', 'B') in bridge.calls
    assert ('connect', 'A') not in bridge.calls
    assert result == {'examined': 2, 'created': 1, 'connected': 1, 'failed': 1}
