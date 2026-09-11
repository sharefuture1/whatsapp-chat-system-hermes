"""FR-AI-013: reply language follows inbound text, never operator locale."""
import pytest
from sqlalchemy import create_engine, select

from test_auto_reply_worker import _SettingsManager, _seed_auto_reply_job
from whatsapp_chat_system.ai.auto_reply_worker import AutoReplyWorker
from whatsapp_chat_system.ai.provider import AIResult
from whatsapp_chat_system.db import Base, create_session_factory
from whatsapp_chat_system.db.models import AnalysisJob, Conversation, Message, OutboxMessage


@pytest.mark.parametrize(('text', 'reply', 'language'), [
    ('สวัสดีครับ ร้านเปิดกี่โมงครับ', 'สวัสดีครับ ขอสอบถามข้อมูลร้านเพิ่มเติมครับ', 'Thai'),
    ('ສະບາຍດີ', 'ສະບາຍດີ ມີຫຍັງໃຫ້ຊ່ວຍ?', 'Lao'),
    ('你好，请问怎么预约？', '你好，请告诉我你想预约的日期。', 'Chinese'),
    ('Hello, how can I book?', 'Hello, which day would you like to book?', 'English/Latin'),
])
def test_worker_pins_language_to_inbound_message(tmp_path, text, reply, language):
    engine = create_engine(f"sqlite:///{tmp_path / 'language.db'}")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    _seed_auto_reply_job(factory)
    with factory() as session:
        session.scalar(select(Message)).content = text
        session.commit()
    seen = []

    class Provider:
        def chat(self, **kwargs):
            seen.extend(kwargs['messages'])
            return AIResult(reply, kwargs['model'], None, {}, 1)

    worker = AutoReplyWorker(factory, _SettingsManager(), provider_factory=lambda _: Provider())
    worker.run_once()
    assert language in seen[0]['content']
    assert seen[-1]['content'] == text
    with factory() as session:
        assert session.query(OutboxMessage).count() == 1
    engine.dispose()


@pytest.mark.parametrize('opt_out', [False, True])
def test_wrong_language_or_late_optout_never_enters_outbox(tmp_path, opt_out):
    engine = create_engine(f"sqlite:///{tmp_path / 'blocked.db'}")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    _seed_auto_reply_job(factory)
    with factory() as session:
        session.scalar(select(Message)).content = 'สวัสดีครับ ขอสอบถามราคา'
        session.commit()

    class Provider:
        def chat(self, **kwargs):
            if opt_out:
                with factory() as session:
                    session.scalar(select(Conversation)).ai_mode = 'off'
                    session.commit()
            return AIResult('สวัสดีครับ' if opt_out else '你好', kwargs['model'], None, {}, 1)

    worker = AutoReplyWorker(factory, _SettingsManager(), provider_factory=lambda _: Provider())
    worker.run_once()
    with factory() as session:
        assert session.query(OutboxMessage).count() == 0
        assert session.scalar(select(AnalysisJob)).status in {'retry', 'cancelled'}
    engine.dispose()
