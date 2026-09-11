from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from whatsapp_chat_system.db.base import Base
from whatsapp_chat_system.db.models import (
    Contact,
    Conversation,
    Message,
    MessageTranslation,
    TranslationBatch,
    WhatsAppAccount,
)
from whatsapp_chat_system.events.inbound_translation import (
    enqueue_for_inbound_translation,
    is_translatable_text,
)
from whatsapp_chat_system.translations_dispatcher import (
    TranslationDispatcher,
)


def _setup_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    with factory() as session:
        account = WhatsAppAccount(id="acc-1", name="Test Account", status="online", enabled=True, session_ref="account:acc-1")
        session.add(account)
        contact = Contact(id="c-1", account_id="acc-1", remote_jid="12345@s.whatsapp.net", display_name="User")
        session.add(contact)
        conv = Conversation(
            id="conv-1",
            account_id="acc-1",
            remote_jid="12345@s.whatsapp.net",
            contact_id="c-1",
            title="Chat 1",
        )
        session.add(conv)
        session.commit()
    return factory


def test_is_translatable_text():
    assert not is_translatable_text("")
    assert not is_translatable_text("   ")
    assert not is_translatable_text("1234567")
    assert not is_translatable_text("https://example.com/foo")
    assert not is_translatable_text("你好，世界！")
    assert is_translatable_text("Hello world")
    assert is_translatable_text("สบายดีบ่")  # Lao
    assert is_translatable_text("สวัสดีครับ")  # Thai


def test_inbound_chinese_message_skips_ai():
    factory = _setup_db()
    with factory() as session:
        account = session.get(WhatsAppAccount, "acc-1")
        conv = session.get(Conversation, "conv-1")
        msg = Message(
            id="msg-zh",
            account_id="acc-1",
            conversation_id="conv-1",
            direction="inbound",
            message_type="text",
            content="你好，在吗？",
            wa_message_id="wa-zh",
            status="received",
            occurred_at=datetime.now(timezone.utc),
        )
        session.add(msg)
        session.commit()

        result = enqueue_for_inbound_translation(session, account, conv, msg)
        session.commit()

        # Chinese does not create a batch
        assert result is None
        batches = session.scalars(select(TranslationBatch)).all()
        assert len(batches) == 0

        # And writes a completed MessageTranslation directly
        trans = session.scalar(select(MessageTranslation).where(MessageTranslation.message_id == "msg-zh"))
        assert trans is not None
        assert trans.status == "completed"
        assert trans.source_lang == "Chinese"
        assert trans.translated_text is None


def test_inbound_foreign_message_enqueues_batch_when_no_cache():
    factory = _setup_db()
    with factory() as session:
        account = session.get(WhatsAppAccount, "acc-1")
        conv = session.get(Conversation, "conv-1")
        msg = Message(
            id="msg-th-1",
            account_id="acc-1",
            conversation_id="conv-1",
            direction="inbound",
            message_type="text",
            content="สวัสดีครับ ขอสอบถามราคา",
            wa_message_id="wa-th-1",
            status="received",
            occurred_at=datetime.now(timezone.utc),
        )
        session.add(msg)
        session.commit()

        batch_id = enqueue_for_inbound_translation(session, account, conv, msg)
        session.commit()

        assert batch_id is not None
        batch = session.get(TranslationBatch, batch_id)
        assert batch is not None
        assert batch.anchor_message_id == "msg-th-1"
        assert batch.status == "pending"


def test_inbound_foreign_message_reuses_global_hash_cache_with_zero_ai():
    factory = _setup_db()
    raw_text = "สบายดี ขอเบิ่งสินค้าแหน่"
    text_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()

    with factory() as session:
        # Pre-seed an existing completed translation in the database for another conversation
        existing = MessageTranslation(
            id="trans-old",
            account_id="acc-1",
            conversation_id="conv-other",
            message_id="msg-old",
            source_text_hash=text_hash,
            source_lang="Lao",
            target_lang="zh-CN",
            translated_text="你好，想看看商品",
            status="completed",
            provider="gpt-5.3-codex-spark",
            model="gpt-5.3-codex-spark",
            context_window_size=1,
        )
        session.add(existing)
        session.commit()

        account = session.get(WhatsAppAccount, "acc-1")
        conv = session.get(Conversation, "conv-1")
        new_msg = Message(
            id="msg-new",
            account_id="acc-1",
            conversation_id="conv-1",
            direction="inbound",
            message_type="text",
            content=raw_text,
            wa_message_id="wa-new",
            status="received",
            occurred_at=datetime.now(timezone.utc),
        )
        session.add(new_msg)
        session.commit()

        # Enqueue should detect the global content hash and reuse it immediately!
        result = enqueue_for_inbound_translation(session, account, conv, new_msg)
        session.commit()

        # No batch enqueued
        assert result is None
        batches = session.scalars(select(TranslationBatch)).all()
        assert len(batches) == 0

        # Translation created immediately with existing text!
        new_trans = session.scalar(select(MessageTranslation).where(MessageTranslation.message_id == "msg-new"))
        assert new_trans is not None
        assert new_trans.status == "completed"
        assert new_trans.translated_text == "你好，想看看商品"
        assert new_trans.source_lang == "Lao"


def test_dispatcher_build_plan_reuses_global_hash_cache():
    factory = _setup_db()
    raw_text = "Good morning, how are you?"
    text_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()

    with factory() as session:
        # Seed an existing translation
        session.add(MessageTranslation(
            id="trans-seed",
            account_id="acc-1",
            conversation_id="conv-seed",
            message_id="msg-seed",
            source_text_hash=text_hash,
            source_lang="Latin",
            target_lang="zh-CN",
            translated_text="早上好，你好吗？",
            status="completed",
            provider="test-model",
            model="test-model",
            context_window_size=1,
        ))
        msg = Message(
            id="msg-test-2",
            account_id="acc-1",
            conversation_id="conv-1",
            direction="inbound",
            message_type="text",
            content=raw_text,
            wa_message_id="wa-test-2",
            status="received",
            occurred_at=datetime.now(timezone.utc),
        )
        session.add(msg)
        batch = TranslationBatch(
            id="batch-1",
            account_id="acc-1",
            conversation_id="conv-1",
            anchor_message_id="msg-test-2",
            target_lang="zh-CN",
            window_size=5,
            status="pending",
        )
        session.add(batch)
        session.commit()

        dispatcher = TranslationDispatcher(factory, runtime=None)
        plan = dispatcher._build_plan(session, batch, [msg])
        session.commit()

        # Plan items (pending AI calls) should be EMPTY because it was satisfied by the global hash cache!
        assert len(plan.items) == 0

        # And the new message should now have its MessageTranslation written as completed
        trans = session.scalar(select(MessageTranslation).where(MessageTranslation.message_id == "msg-test-2"))
        assert trans is not None
        assert trans.status == "completed"
        assert trans.translated_text == "早上好，你好吗？"
