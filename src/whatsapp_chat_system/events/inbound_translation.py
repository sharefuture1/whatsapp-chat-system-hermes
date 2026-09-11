from __future__ import annotations

import re
from uuid import uuid4
from sqlalchemy import select
from sqlalchemy.orm import Session

from whatsapp_chat_system.db.models import (
    Conversation,
    Message,
    MessageTranslation,
    TranslationBatch,
    WhatsAppAccount,
)


from whatsapp_chat_system.translation_hash import source_text_hash


def detect_language_hint(text: str) -> str:
    if not text:
        return "Unknown"
    if re.search(r"[\u0E80-\u0EFF]", text):
        return "Lao"
    if re.search(r"[\u0E00-\u0E7F]", text):
        return "Thai"
    if re.search(r"[\u4E00-\u9FFF]", text):
        return "Chinese"
    if re.search(r"[A-Za-z]", text):
        return "Latin"
    return "Unknown"


def is_translatable_text(text: str) -> bool:
    content = (text or "").strip()
    if not content:
        return False
    # Filter pure URLs
    if re.match(r"^https?://\S+$", content, re.IGNORECASE):
        return False
    # Filter pure digits, punctuation, and spaces
    if re.match(r"^[\d\s\W_]+$", content) and not re.search(
        r"[\u0E80-\u0EFF\u0E00-\u0E7FA-Za-z]", content
    ):
        return False
    lang = detect_language_hint(content)
    if lang == "Chinese":
        return False
    return lang in {"Lao", "Thai", "Latin", "Unknown"}


def enqueue_for_inbound_translation(
    session: Session,
    account: WhatsAppAccount,
    conversation: Conversation,
    message: Message,
    target_lang: str = "zh-CN",
    window_size: int = 10,
) -> str | None:
    """入站消息翻译异步入队或就地完成。

    1. 纯中文消息：直接落 completed 记录，无需调用 AI；
    2. 账号内哈希命中：复用当前账号相同原文的已完成译文，0 次外部 AI 调用直接落库；
    3. 首次出现外语：入队 TranslationBatch，由后台 TranslationDispatcher 异步处理。
    """
    if message.direction != "inbound":
        return None
    content = message.content or ""
    if not content.strip():
        return None

    lang = detect_language_hint(content)
    text_hash = source_text_hash(content)

    # 1. 如果已存在当前消息的翻译记录，直接跳过
    current_trans = session.scalar(
        select(MessageTranslation).where(
            MessageTranslation.account_id == account.id,
            MessageTranslation.conversation_id == conversation.id,
            MessageTranslation.message_id == message.id,
            MessageTranslation.target_lang == target_lang,
            MessageTranslation.source_text_hash == text_hash,
        )
    )
    if current_trans is not None and current_trans.status == "completed":
        return None

    # 2. 如果是纯中文或无需翻译文本，直接落库 completed 且 translated_text=None
    if not is_translatable_text(content):
        if lang == "Chinese":
            if current_trans is None:
                trans = MessageTranslation(
                    id=str(uuid4()),
                    account_id=account.id,
                    conversation_id=conversation.id,
                    message_id=message.id,
                    source_text=content,
                    source_text_hash=text_hash,
                    source_lang="Chinese",
                    target_lang=target_lang,
                    translated_text=None,
                    status="completed",
                    provider="direct",
                    model="direct",
                    context_window_size=1,
                )
                session.add(trans)
        return None

    # 3. 账号内翻译记忆库查询（Translation Memory）：当前账号查找相同原文哈希的历史译文
    cached = session.scalar(
        select(MessageTranslation)
        .where(
            MessageTranslation.account_id == account.id,
            MessageTranslation.target_lang == target_lang,
            MessageTranslation.source_text_hash == text_hash,
            MessageTranslation.status == "completed",
            MessageTranslation.translated_text.is_not(None),
        )
        .order_by(MessageTranslation.updated_at.desc(), MessageTranslation.id.desc())
        .limit(1)
    )
    if cached is not None and cached.translated_text:
        # 账号内缓存命中！复用历史译文，无需创建批次，无需调用 AI
        if current_trans is None:
            trans = MessageTranslation(
                id=str(uuid4()),
                account_id=account.id,
                conversation_id=conversation.id,
                message_id=message.id,
                source_text=content,
                source_text_hash=text_hash,
                source_lang=cached.source_lang or lang,
                target_lang=target_lang,
                translated_text=cached.translated_text,
                status="completed",
                provider=cached.provider or "cache_memory",
                model=cached.model or "cache_memory",
                context_window_size=1,
            )
            session.add(trans)
        else:
            current_trans.source_text = content
            current_trans.error_code = None
            current_trans.error_message = None
            current_trans.source_text_hash = text_hash
            current_trans.source_lang = cached.source_lang or lang
            current_trans.translated_text = cached.translated_text
            current_trans.status = "completed"
            current_trans.provider = cached.provider or "cache_memory"
            current_trans.model = cached.model or "cache_memory"
        return None

    # 4. 检查是否已有该会话的活动批次覆盖此消息
    active_batch = session.scalar(
        select(TranslationBatch)
        .where(
            TranslationBatch.account_id == account.id,
            TranslationBatch.conversation_id == conversation.id,
            TranslationBatch.anchor_message_id == message.id,
            TranslationBatch.target_lang == target_lang,
            TranslationBatch.status.in_(("pending", "claimed", "running")),
        )
        .order_by(TranslationBatch.created_at.desc())
        .limit(1)
    )
    if active_batch is not None:
        return active_batch.id

    # 5. 未命中账号内缓存：入队 TranslationBatch，交由后台 Worker 处理
    batch = TranslationBatch(
        id=str(uuid4()),
        account_id=account.id,
        conversation_id=conversation.id,
        anchor_message_id=message.id,
        target_lang=target_lang,
        window_size=window_size,
        status="pending",
    )
    session.add(batch)
    return batch.id
