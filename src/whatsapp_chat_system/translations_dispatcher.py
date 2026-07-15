from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db.models import Message, MessageTranslation, TranslationBatch
from .rewriter import Rewriter

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TranslationDispatcherConfig:
    poll_seconds: float = 2.0


class TranslationDispatcher:
    def __init__(self, session_factory: Callable[[], Session], runtime: Any, *, runtime_manager: Any = None, config: TranslationDispatcherConfig | None = None) -> None:
        self.session_factory = session_factory
        self.runtime = runtime
        self.runtime_manager = runtime_manager
        self.config = config or TranslationDispatcherConfig()
        self.last_heartbeat: datetime | None = None
        self.last_error: str | None = None
        self.processed_batches = 0
        self.failed_batches = 0

    def run_once(self) -> bool:
        self.last_heartbeat = datetime.now(timezone.utc)
        with self.session_factory() as session:
            batch = session.scalar(select(TranslationBatch).where(
                TranslationBatch.status == 'pending'
            ).order_by(TranslationBatch.created_at.asc()))
            if batch is None:
                return False
            try:
                self._process_batch(session, batch)
                session.commit()
                self.processed_batches += 1
                return True
            except Exception as exc:
                session.rollback()
                self.failed_batches += 1
                self.last_error = type(exc).__name__
                logger.exception('Translation batch failed', extra={'batch_id': batch.id})
                with self.session_factory() as retry_session:
                    row = retry_session.get(TranslationBatch, batch.id)
                    if row is not None:
                        row.status = 'failed'
                        row.error_code = 'translation_batch_failed'
                        row.error_message = str(exc)
                        retry_session.commit()
                return False

    def _process_batch(self, session: Session, batch: TranslationBatch) -> None:
        batch.status = 'running'
        anchor = session.get(Message, batch.anchor_message_id)
        if anchor is None:
            batch.status = 'dead'
            batch.error_code = 'anchor_message_missing'
            batch.completed_at = datetime.now(timezone.utc)
            return
        rows = session.scalars(select(Message).where(
            Message.conversation_id == batch.conversation_id,
            func.coalesce(Message.occurred_at, Message.created_at) <= func.coalesce(anchor.occurred_at, anchor.created_at),
        ).order_by(func.coalesce(Message.occurred_at, Message.created_at).desc(), Message.id.desc()).limit(batch.window_size)).all()
        rows.reverse()
        worker = self._rewriter()
        pending_items: list[dict[str, Any]] = []
        for message in rows:
            text = (message.content or '').strip()
            if not text:
                continue
            source_lang = self._language_hint_for(text)
            source_hash = self._source_text_hash(text)
            existing = session.scalar(select(MessageTranslation).where(
                MessageTranslation.message_id == message.id,
                MessageTranslation.target_lang == batch.target_lang,
                MessageTranslation.source_text_hash == source_hash,
                MessageTranslation.status == 'completed',
            ))
            if existing is not None:
                continue
            if source_lang == 'Chinese':
                self._upsert_translation(session, message, batch, source_lang=source_lang, translated_text=None, status='completed')
                continue
            pending_items.append({
                'message': message,
                'text': text,
                'source_lang': source_lang,
            })
        if pending_items:
            batch_result = self._translate_window(worker, pending_items)
            for item in pending_items:
                message = item['message']
                result = batch_result.get(message.id)
                if result is None:
                    fallback = worker.translate_to_zh_result(item['text'], item['source_lang'])
                    fallback_text = (fallback.message or '').strip()
                    has_usable_translation = bool(fallback_text and fallback_text != item['text'].strip())
                    if fallback.error and not has_usable_translation:
                        self._upsert_translation(session, message, batch, source_lang=item['source_lang'], translated_text=None, status='failed', error_code='translate_failed', error_message=str(fallback.error))
                    else:
                        self._upsert_translation(session, message, batch, source_lang=item['source_lang'], translated_text=fallback_text or None, status='completed')
                    continue
                if result.get('error'):
                    self._upsert_translation(session, message, batch, source_lang=str(result.get('source_lang') or item['source_lang']), translated_text=None, status='failed', error_code='translate_failed', error_message=str(result['error']))
                else:
                    self._upsert_translation(session, message, batch, source_lang=str(result.get('source_lang') or item['source_lang']), translated_text=str(result.get('translated_text') or '') or None, status='completed')
        batch.status = 'completed'
        batch.error_code = None
        batch.error_message = None
        batch.completed_at = datetime.now(timezone.utc)

    def _translate_window(self, worker: Rewriter, pending_items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        phrase_dict = worker.phrase_dict
        context_block = ''
        if phrase_dict:
            entries = list(phrase_dict.items())[:120]
            dict_section = '\n'.join(f'  "{k}" → "{v}"' for k, v in entries)
            context_block = f"# 已知正确翻译\n{dict_section}\n\n"
        payload_items = [
            {
                'message_id': item['message'].id,
                'source_lang': item['source_lang'],
                'text': item['text'],
            }
            for item in pending_items
        ]
        prompt = (
            "你是一个高精度聊天翻译器。请把输入 items 中每条消息翻译成简体中文。\n"
            "要求：\n"
            "1. 保留语气、情感、emoji。\n"
            "2. 不要合并消息，不要漏项。\n"
            "3. 若原文已经是中文，zh 置为空字符串。\n"
            "4. 只输出合法 JSON：{\"items\":[{\"message_id\":\"...\",\"source_lang\":\"...\",\"zh\":\"...\"}]}。\n\n"
            + context_block
            + json.dumps({'items': payload_items}, ensure_ascii=False)
        )
        try:
            result = worker.ai_service.chat(
                messages=[
                    {'role': 'system', 'content': '你只返回合法 JSON，不要输出解释。'},
                    {'role': 'user', 'content': prompt},
                ],
                account_model=worker._account_model(),
                temperature=0.1,
                response_format={'type': 'json_object'},
            )
            parsed = json.loads(result.result.content)
            items = parsed.get('items') or []
            output: dict[str, dict[str, Any]] = {}
            for row in items:
                message_id = str(row.get('message_id') or '').strip()
                if not message_id:
                    continue
                output[message_id] = {
                    'source_lang': str(row.get('source_lang') or ''),
                    'translated_text': str(row.get('zh') or '').strip() or None,
                }
            return output
        except Exception as exc:
            logger.warning('Translation window batch call failed; falling back to per-message translate', extra={'error': str(exc), 'items': len(pending_items)})
            return {}

    def _rewriter(self) -> Rewriter:
        class _DummyAppPaths:
            memory_dir: Any
            def __init__(self, memory_dir: Any) -> None:
                self.memory_dir = memory_dir

        class _DummyConfig:
            paths: _DummyAppPaths
            ai_settings: Any
            def __init__(self, memory_dir: Any, ai_settings: Any) -> None:
                self.paths = _DummyAppPaths(memory_dir)
                self.ai_settings = ai_settings

        config = _DummyConfig(self.runtime.paths.memory_dir, self.runtime.ai_settings)
        return Rewriter(config, lambda *args, **kwargs: None, runtime_manager=self.runtime_manager)

    @staticmethod
    def _language_hint_for(text: str) -> str:
        import re
        if not text:
            return 'Unknown'
        if re.search(r"[\u0E80-\u0EFF]", text):
            return 'Lao'
        if re.search(r"[\u0E00-\u0E7F]", text):
            return 'Thai'
        if re.search(r"[\u4E00-\u9FFF]", text):
            return 'Chinese'
        if re.search(r"[A-Za-z]", text):
            return 'Latin'
        return 'Unknown'

    @staticmethod
    def _source_text_hash(text: str) -> str:
        return hashlib.sha256((text or '').encode('utf-8')).hexdigest()

    @staticmethod
    def _upsert_translation(session: Session, message: Message, batch: TranslationBatch, *, source_lang: str, translated_text: str | None, status: str, error_code: str | None = None, error_message: str | None = None) -> MessageTranslation:
        source_hash = TranslationDispatcher._source_text_hash(message.content or '')
        row = session.scalar(select(MessageTranslation).where(
            MessageTranslation.message_id == message.id,
            MessageTranslation.target_lang == batch.target_lang,
            MessageTranslation.source_text_hash == source_hash,
        ))
        if row is None:
            row = MessageTranslation(
                account_id=message.account_id,
                conversation_id=message.conversation_id,
                message_id=message.id,
                target_lang=batch.target_lang,
                source_text_hash=source_hash,
            )
            session.add(row)
        row.source_text = message.content or ''
        row.source_lang = source_lang
        row.translated_text = translated_text
        row.status = status
        row.error_code = error_code
        row.error_message = error_message
        row.provider = 'wendingai'
        row.context_window_size = batch.window_size
        row.batch_id = batch.id
        row.completed_at = datetime.now(timezone.utc) if status == 'completed' else None
        return row

    def health(self) -> dict[str, Any]:
        return {
            'last_heartbeat': self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            'last_error': self.last_error,
            'processed_batches': self.processed_batches,
            'failed_batches': self.failed_batches,
        }
