from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, value: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(value, encoding="utf-8")


def replace(path: str, old: str, new: str, *, sentinel: str | None = None) -> None:
    text = read(path)
    if sentinel and sentinel in text:
        return
    if old not in text:
        raise RuntimeError(f"patch target missing: {path}: {old[:100]!r}")
    write(path, text.replace(old, new, 1))


def regex(path: str, pattern: str, replacement: str, *, sentinel: str) -> None:
    text = read(path)
    if sentinel in text:
        return
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"regex patch target missing: {path}: {pattern[:100]!r}")
    write(path, updated)


# ---------------------------------------------------------------------------
# Python API: account-aware controls + outbox queue
# ---------------------------------------------------------------------------
conversations = "src/whatsapp_chat_system/api/v1/conversations.py"
replace(
    conversations,
    "from typing import Any\n",
    "from typing import Any\nfrom uuid import uuid4\n",
    sentinel="from uuid import uuid4",
)
replace(
    conversations,
    "    Contact,\n    Conversation,\n",
    "    Contact,\n    ContactAIOverride,\n    Conversation,\n",
    sentinel="ContactAIOverride,",
)
replace(
    conversations,
    ")\n\n\nPLATFORM = \"whatsapp\"\n",
    ")\nfrom whatsapp_chat_system.outbox import enqueue_outbox_message\n\n\nPLATFORM = \"whatsapp\"\n",
    sentinel="from whatsapp_chat_system.outbox import enqueue_outbox_message",
)
replace(
    conversations,
    "class ConversationReplyRequest(BaseModel):\n    message: str = Field(min_length=1, max_length=10000)\n",
    """class ConversationReplyRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10000)
    idempotency_key: str | None = Field(default=None, max_length=255)


class ConversationStateUpdate(BaseModel):
    pinned: bool | None = None
    muted: bool | None = None
    archived: bool | None = None
""",
    sentinel="class ConversationStateUpdate",
)
replace(
    conversations,
    """            select(Conversation, Contact, WhatsAppAccount)
            .join(WhatsAppAccount, WhatsAppAccount.id == Conversation.account_id)
            .outerjoin(Contact, Contact.id == Conversation.contact_id)
""",
    """            select(Conversation, Contact, WhatsAppAccount, ContactAIOverride)
            .join(WhatsAppAccount, WhatsAppAccount.id == Conversation.account_id)
            .outerjoin(Contact, Contact.id == Conversation.contact_id)
            .outerjoin(
                ContactAIOverride,
                and_(
                    ContactAIOverride.account_id == Conversation.account_id,
                    ContactAIOverride.contact_id == Conversation.contact_id,
                ),
            )
""",
    sentinel="select(Conversation, Contact, WhatsAppAccount, ContactAIOverride)",
)
replace(
    conversations,
    '                "platform": PLATFORM,\n',
    '''                "contact_id": conversation.contact_id,
                "contact_profile": {
                    "remark": contact.remark if contact else None,
                    "notes": contact.notes if contact else None,
                    "tags": (contact.tags or []) if contact else [],
                    "language": contact.language if contact else None,
                },
                "user_override": {
                    "ai_model": override.model if override else None,
                    "custom_system_prompt": override.system_prompt if override else None,
                    "reply_style": override.reply_style if override else None,
                    "auto_reply_enabled": override.auto_reply_enabled if override else None,
                },
                "platform": PLATFORM,
''',
    sentinel='"contact_profile": {',
)
replace(
    conversations,
    "            for conversation, contact, account in rows\n",
    "            for conversation, contact, account, override in rows\n",
    sentinel="for conversation, contact, account, override in rows",
)
replace(
    conversations,
    """            select(Contact, WhatsAppAccount, Conversation)
            .join(WhatsAppAccount, WhatsAppAccount.id == Contact.account_id)
            .outerjoin(
                Conversation,
""",
    """            select(Contact, WhatsAppAccount, Conversation, ContactAIOverride)
            .join(WhatsAppAccount, WhatsAppAccount.id == Contact.account_id)
            .outerjoin(
                Conversation,
""",
    sentinel="select(Contact, WhatsAppAccount, Conversation, ContactAIOverride)",
)
replace(
    conversations,
    """                & Conversation.deleted_at.is_(None),
            )
        )
""",
    """                & Conversation.deleted_at.is_(None),
            )
            .outerjoin(
                ContactAIOverride,
                and_(
                    ContactAIOverride.account_id == Contact.account_id,
                    ContactAIOverride.contact_id == Contact.id,
                ),
            )
        )
""",
    sentinel="ContactAIOverride.contact_id == Contact.id",
)
replace(
    conversations,
    '                "notes": contact.notes,\n',
    '''                "notes": contact.notes,
                "user_override": {
                    "ai_model": override.model if override else None,
                    "custom_system_prompt": override.system_prompt if override else None,
                    "reply_style": override.reply_style if override else None,
                    "auto_reply_enabled": override.auto_reply_enabled if override else None,
                },
''',
    sentinel='"user_override": {\n                    "ai_model": override.model',
)
replace(
    conversations,
    "            for contact, account, conversation in rows\n",
    "            for contact, account, conversation, override in rows\n",
    sentinel="for contact, account, conversation, override in rows",
)
replace(
    conversations,
    """    @router.delete("/conversations/{conversation_id}")
    def delete_conversation(
""",
    """    @router.patch("/conversations/{conversation_id}")
    def update_conversation_state(
        conversation_id: str,
        payload: ConversationStateUpdate,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        conversation = session.get(Conversation, conversation_id)
        if conversation is None or conversation.deleted_at is not None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        changes = payload.model_dump(exclude_unset=True)
        if not changes:
            raise HTTPException(status_code=422, detail="No state changes provided")
        for key, value in changes.items():
            setattr(conversation, key, value)
        session.commit()
        return {
            "success": True,
            "conversation_id": conversation.id,
            "account_id": conversation.account_id,
            "pinned": conversation.pinned,
            "muted": conversation.muted,
            "archived": conversation.archived,
        }

    @router.post("/conversations/{conversation_id}/read")
    def mark_conversation_read(
        conversation_id: str,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        conversation = session.get(Conversation, conversation_id)
        if conversation is None or conversation.deleted_at is not None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        conversation.unread_count = 0
        session.commit()
        return {
            "success": True,
            "conversation_id": conversation.id,
            "unread_count": 0,
        }

    @router.delete("/conversations/{conversation_id}")
    def delete_conversation(
""",
    sentinel="def update_conversation_state(",
)
replace(
    conversations,
    '                "status": message.status,\n                "lang": "Unknown",\n',
    '''                "status": message.status,
                "pending": message.status in {"queued", "sending"},
                "failed": message.status == "failed",
                "sent": message.status in {"sent", "delivered", "read"},
                "error": message.error_message,
                "retryable": message.status != "failed" or message.retry_count < 6,
                "lang": "Unknown",
''',
    sentinel='"pending": message.status in {"queued", "sending"}',
)
regex(
    conversations,
    r'''    @router\.post\("/conversations/\{conversation_id\}/reply"\)\n    def reply_to_conversation\(.*?\n        return \{\n            "success": True,\n            "local_message_id": message\.id,\n            "message_id": message\.wa_message_id,\n            "account_id": conversation\.account_id,\n            "conversation_id": conversation\.id,\n        \}\n''',
    '''    @router.post("/conversations/{conversation_id}/reply", status_code=202)
    def reply_to_conversation(
        conversation_id: str,
        payload: ConversationReplyRequest,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        conversation = session.get(Conversation, conversation_id)
        if conversation is None or conversation.deleted_at is not None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        idempotency_key = payload.idempotency_key or f"reply:{uuid4()}"
        if not idempotency_key.startswith("reply:"):
            idempotency_key = f"reply:{idempotency_key}"
        try:
            message, outbox, created = enqueue_outbox_message(
                session,
                conversation,
                text=payload.message,
                idempotency_key=idempotency_key,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        session.commit()
        return {
            "success": True,
            "created": created,
            "queued": outbox.status in {"pending", "claimed"},
            "status": message.status,
            "local_message_id": message.id,
            "message_id": message.wa_message_id,
            "outbox_id": outbox.id,
            "account_id": conversation.account_id,
            "conversation_id": conversation.id,
        }
''',
    sentinel='"outbox_id": outbox.id',
)

accounts = "src/whatsapp_chat_system/api/v1/accounts.py"
replace(
    accounts,
    "    def send(self, account_id: str, *, chat_id: str, text: str) -> dict[str, Any]: ...\n",
    """    def send(
        self,
        account_id: str,
        *,
        chat_id: str,
        text: str,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]: ...
""",
    sentinel="idempotency_key: str | None = None",
)

# ---------------------------------------------------------------------------
# Standalone app: routers + workers
# ---------------------------------------------------------------------------
standalone = "src/whatsapp_chat_system/standalone_api.py"
replace(
    standalone,
    "from .api.v1.personas import create_personas_router\n",
    """from .api.v1.personas import create_personas_router
from .api.v1.operations import create_operations_router
from .api.v1.settings import create_settings_router
""",
    sentinel="from .api.v1.settings import create_settings_router",
)
replace(
    standalone,
    "from .runtime import StandaloneRuntime, save_runtime_settings\n",
    """from .outbox import OutboxDispatcher
from .runtime import StandaloneRuntime, save_runtime_settings
""",
    sentinel="from .outbox import OutboxDispatcher",
)
replace(
    standalone,
    "    account_reconcile_interval_seconds: float = 45.0,\n",
    """    account_reconcile_interval_seconds: float = 45.0,
    outbox_poll_interval_seconds: float = 1.0,
""",
    sentinel="outbox_poll_interval_seconds",
)
replace(
    standalone,
    "    reconciler = AccountReconciler(factory, bridge)\n    login_lock = RLock()\n",
    """    reconciler = AccountReconciler(factory, bridge)
    outbox_dispatcher = OutboxDispatcher(factory, bridge)
    login_lock = RLock()
""",
    sentinel="outbox_dispatcher = OutboxDispatcher",
)
regex(
    standalone,
    r'''        task = asyncio\.create_task\(reconcile_loop\(\), name="whatsapp-account-reconciler"\)\n        app\.state\.account_reconciler_task = task\n        try:\n            yield\n        finally:\n            app\.state\.ready = False\n            task\.cancel\(\)\n            await asyncio\.gather\(task, return_exceptions=True\)\n''',
    '''        async def outbox_loop() -> None:
            while True:
                try:
                    processed = await asyncio.to_thread(outbox_dispatcher.run_once)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Outbound message worker round failed")
                    processed = 0
                await asyncio.sleep(0 if processed else outbox_poll_interval_seconds)

        reconcile_task = asyncio.create_task(
            reconcile_loop(), name="whatsapp-account-reconciler"
        )
        outbox_task = asyncio.create_task(outbox_loop(), name="whatsapp-outbox-worker")
        app.state.account_reconciler_task = reconcile_task
        app.state.outbox_worker_task = outbox_task
        try:
            yield
        finally:
            app.state.ready = False
            reconcile_task.cancel()
            outbox_task.cancel()
            await asyncio.gather(reconcile_task, outbox_task, return_exceptions=True)
''',
    sentinel="name=\"whatsapp-outbox-worker\"",
)
replace(
    standalone,
    'app = FastAPI(title="WhatsApp Chat System API", version="0.5.3", lifespan=lifespan)',
    'app = FastAPI(title="WhatsApp Chat System API", version="0.6.0", lifespan=lifespan)',
    sentinel='version="0.6.0"',
)
replace(
    standalone,
    '            "X-Request-ID",\n',
    '            "X-Request-ID",\n            "Idempotency-Key",\n',
    sentinel='"Idempotency-Key"',
)
replace(
    standalone,
    "    app.include_router(create_personas_router(runtime, factory))\n",
    """    app.include_router(create_personas_router(runtime, factory))
    app.include_router(create_settings_router(runtime, factory))
    app.include_router(create_operations_router(factory))
""",
    sentinel="create_operations_router(factory)",
)
replace(
    standalone,
    '                "login_enabled": True,\n',
    '                "login_enabled": True,\n                "outbox_worker": "running",\n',
    sentinel='"outbox_worker": "running"',
)

# ---------------------------------------------------------------------------
# Bridge: durable idempotency receipt store
# ---------------------------------------------------------------------------
server = "bridge/src/server.js"
replace(
    server,
    """function requiredString(body, key) {
  const value = body[key];
  if (typeof value !== 'string' || !value.trim()) {
    throw new BridgeDomainError('invalid_body', `${key} must be a non-empty string`, { status: 400 });
  }
  return value.trim();
}
""",
    """function requiredString(body, key) {
  const value = body[key];
  if (typeof value !== 'string' || !value.trim()) {
    throw new BridgeDomainError('invalid_body', `${key} must be a non-empty string`, { status: 400 });
  }
  return value.trim();
}

function optionalIdempotencyKey(body) {
  const value = body.idempotency_key;
  if (value === undefined || value === null || value === '') return null;
  if (typeof value !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$/.test(value)) {
    throw new BridgeDomainError('invalid_idempotency_key', 'Invalid idempotency_key', { status: 400 });
  }
  return value;
}
""",
    sentinel="function optionalIdempotencyKey",
)
replace(
    server,
    "        const messageId = await manager.send(sendId, { chatId, text });\n",
    """        const idempotencyKey = optionalIdempotencyKey(body);
        const messageId = await manager.send(sendId, { chatId, text, idempotencyKey });
""",
    sentinel="const idempotencyKey = optionalIdempotencyKey(body)",
)

session = "bridge/src/account-session.js"
replace(
    session,
    "import { normalizeChat, normalizeContact, occurrenceChunkIdentity } from './sync-normalizer.js';\n",
    """import { normalizeChat, normalizeContact, occurrenceChunkIdentity } from './sync-normalizer.js';
import { SendReceiptStore } from './send-receipt-store.js';
""",
    sentinel="SendReceiptStore",
)
replace(
    session,
    "    this.qrExpiryTimer = null;\n",
    """    this.qrExpiryTimer = null;
    this.sendReceiptStore = new SendReceiptStore(spoolDir);
    this.sendInFlight = new Map();
""",
    sentinel="this.sendReceiptStore",
)
replace(
    session,
    "    await Promise.all([this.sessionDir, this.spoolDir, this.mediaDir].map(secureDirectory));\n",
    """    await Promise.all([this.sessionDir, this.spoolDir, this.mediaDir].map(secureDirectory));
    await this.sendReceiptStore.start();
""",
    sentinel="await this.sendReceiptStore.start()",
)
regex(
    session,
    r'''  async send\(\{ chatId, text \}\) \{.*?\n    return messageId;\n  \}\n''',
    '''  async send({ chatId, text, idempotencyKey = null }) {
    const key = this.sendReceiptStore.validateKey(idempotencyKey);
    if (key) {
      const existing = this.sendReceiptStore.get(key);
      if (existing) return existing;
      if (this.sendInFlight.has(key)) return this.sendInFlight.get(key);
    }
    const operation = this.#sendNow({ chatId, text, idempotencyKey: key });
    if (key) this.sendInFlight.set(key, operation);
    try {
      return await operation;
    } finally {
      if (key && this.sendInFlight.get(key) === operation) this.sendInFlight.delete(key);
    }
  }

  async #sendNow({ chatId, text, idempotencyKey }) {
    if (this.state !== 'online' || !this.socket) {
      throw new BridgeDomainError('account_offline', 'Account is not online', { status: 409, retryable: true });
    }
    const sent = await this.socket.sendMessage(chatId, { text });
    const messageId = sent?.key?.id;
    if (typeof messageId !== 'string' || !messageId.trim()) {
      throw new BridgeDomainError(
        'missing_message_id',
        'WhatsApp did not return a message ID',
        { status: 502, retryable: true },
      );
    }
    if (idempotencyKey) await this.sendReceiptStore.put(idempotencyKey, messageId);
    await this.#emitEvent('message.sent', {
      wa_message_id: messageId,
      timestamp: new Date(this.now()).toISOString(),
      error_code: null,
      error_message: null,
    }, `receipt:${messageId}:message.sent`);
    return messageId;
  }
''',
    sentinel="async #sendNow({ chatId, text, idempotencyKey })",
)

# ---------------------------------------------------------------------------
# Frontend V1 single-source migration path
# ---------------------------------------------------------------------------
app = "web/src/App.jsx"
regex(
    app,
    r'''  const fetchConversationsPage = useCallback\(async \(page\) => \{.*?\n  \}, \[\]\)\n''',
    '''  const fetchConversationsPage = useCallback(async (page) => {
    const standaloneRes = await api.get(`/v1/conversations?platform=all&account_id=all&limit=200`)
    const contactsRes = await api.get('/v1/contacts?platform=all&account_id=all&limit=500')
    const legacyResults = await Promise.allSettled([
      api.get(`/conversations?page=${page}&page_size=${PAGE_SIZE}`),
      api.get('/contacts?page=1&page_size=500'),
    ])
    const legacyRes = legacyResults[0].status === 'fulfilled'
      ? legacyResults[0].value
      : { items: [], total: 0, has_more: false }
    const legacyContactsRes = legacyResults[1].status === 'fulfilled'
      ? legacyResults[1].value
      : { items: [] }
    const inbox = buildInbox({
      legacy: legacyRes.items || [],
      standalone: standaloneRes.items || [],
      standaloneAccounts: standaloneRes.available_accounts || accountsRef.current || [],
    })
    return {
      items: inbox.conversations,
      contacts: buildContacts({
        legacy: legacyContactsRes.items || [],
        standalone: contactsRes.items || [],
        accounts: inbox.accounts,
      }),
      accounts: inbox.accounts,
      legacyTotal: Number(legacyRes.total) || 0,
      has_more: Boolean(legacyRes.has_more),
      page,
    }
  }, [])
''',
    sentinel="const standaloneRes = await api.get(`/v1/conversations",
)
replace(
    app,
    """        const convRes = await fetchConversationsPage(1)
        const dashboardRes = await api.get('/dashboard')
        return { convRes, dashboardRes }
""",
    """        const [convRes, dashboardRes] = await Promise.all([
          fetchConversationsPage(1),
          api.get('/v1/dashboard').catch(() => api.get('/dashboard').catch(() => null)),
        ])
        return { convRes, dashboardRes }
""",
    sentinel="api.get('/v1/dashboard')",
)
replace(
    app,
    "        setDashboard(dashboardRes)\n",
    "        if (dashboardRes) setDashboard(dashboardRes)\n",
    sentinel="if (dashboardRes) setDashboard(dashboardRes)",
)
replace(
    app,
    """          setSelectedName('')
          return ''
        })
""",
    """          return prev
        })
""",
)
regex(
    app,
    r'''  const refreshSettings = useCallback\(async \(\) => \{.*?\n  \}, \[\]\)\n''',
    '''  const refreshSettings = useCallback(async () => {
    const [settingsData, aiData] = await Promise.all([
      api.get('/v1/settings').catch(() => api.get('/settings')),
      api.get('/v1/ai/settings').catch(() => ({})),
    ])
    setSettings(settingsData)
    setApiSettings(aiData)
  }, [])
''',
    sentinel="api.get('/v1/settings').catch",
)
replace(
    app,
    "      await api.put('/settings', payload)\n",
    """      await api.put('/v1/settings', {
        channels: payload.channels || settings.channels || [],
        web_settings: payload.web_settings || payload,
      }).catch(() => api.put('/settings', payload))
""",
    sentinel="await api.put('/v1/settings'",
)
replace(
    app,
    "  const sendReply = async (conversation, message, mode, { previewOnly = false } = {}) => {\n",
    "  const sendReply = async (conversation, message, mode, { previewOnly = false, idempotencyKey = null } = {}) => {\n",
    sentinel="idempotencyKey = null",
)
replace(
    app,
    "        ? await api.post(`/v1/conversations/${encodeURIComponent(conversation.conversation_id)}/reply`, { message })\n",
    "        ? await api.post(`/v1/conversations/${encodeURIComponent(conversation.conversation_id)}/reply`, { message, idempotency_key: idempotencyKey })\n",
    sentinel="idempotency_key: idempotencyKey",
)
regex(
    app,
    r'''  const togglePin = useCallback\(async \(userId\) => \{.*?\n  \}, \[pinned, refreshWorkspace\]\)\n''',
    '''  const togglePin = useCallback(async (conversation) => {
    if (!conversation) return
    const pinKey = conversation.conversation_key || conversation.user_id
    const isPinned = pinned.includes(pinKey) || Boolean(conversation.pinned)
    setPinned(prev => {
      const updated = isPinned ? prev.filter(item => item !== pinKey) : [pinKey, ...prev.filter(item => item !== pinKey)]
      localStorage.setItem(PIN_KEY, JSON.stringify(updated))
      return updated
    })
    try {
      if (conversation.source === 'standalone' && conversation.conversation_id) {
        await api.patch(`/v1/conversations/${encodeURIComponent(conversation.conversation_id)}`, { pinned: !isPinned })
      } else {
        await api.post('/chat/pin', { user_id: conversation.user_id, pinned: !isPinned })
      }
      refreshWorkspace({ silent: true, fresh: true })
    } catch (error) {
      setPinned(prev => {
        const rolledBack = isPinned
          ? [pinKey, ...prev.filter(item => item !== pinKey)]
          : prev.filter(item => item !== pinKey)
        localStorage.setItem(PIN_KEY, JSON.stringify(rolledBack))
        return rolledBack
      })
      showError(error)
    }
  }, [pinned, refreshWorkspace])
''',
    sentinel="const pinKey = conversation.conversation_key",
)
replace(
    app,
    "  const markRead = useCallback((userId, ts) => {\n",
    "  const markRead = useCallback((userId, ts, conversation = null) => {\n",
    sentinel="conversation = null",
)
replace(
    app,
    "      setReadTick(prev => prev + 1)\n",
    """      setReadTick(prev => prev + 1)
      if (conversation?.source === 'standalone' && conversation?.conversation_id) {
        api.post(`/v1/conversations/${encodeURIComponent(conversation.conversation_id)}/read`, {}).catch(() => {})
      }
""",
    sentinel="/read`, {}).catch",
)
replace(
    app,
    "      markRead(conversationKey, found.last_timestamp)\n",
    "      markRead(conversationKey, found.last_timestamp, found)\n",
)
replace(
    app,
    "    if (found) markRead(found.conversation_key, found.last_timestamp)\n",
    "    if (found) markRead(found.conversation_key, found.last_timestamp, found)\n",
)
replace(
    app,
    "      const remark = String(contactProfiles[item.user_id]?.remark || '').toLowerCase()\n",
    "      const remark = String(item.contact_profile?.remark || contactProfiles[item.user_id]?.remark || '').toLowerCase()\n",
    sentinel="item.contact_profile?.remark",
)
replace(
    app,
    "    return (settings.web_settings?.contact_profiles || {})[selectedConversation.user_id] || null\n",
    "    return selectedConversation.contact_profile || (settings.web_settings?.contact_profiles || {})[selectedConversation.user_id] || null\n",
    sentinel="return selectedConversation.contact_profile",
)
replace(
    app,
    "    return (settings.web_settings?.reply?.user_overrides || {})[selectedConversation.user_id] || null\n",
    "    return selectedConversation.user_override || (settings.web_settings?.reply?.user_overrides || {})[selectedConversation.user_id] || null\n",
    sentinel="return selectedConversation.user_override",
)
replace(
    app,
    """    setSaving(true)
    try {
      const currentOverrides = settings.web_settings?.reply?.user_overrides || {}
""",
    """    setSaving(true)
    try {
      if (selectedConversation?.source === 'standalone' && selectedConversation?.contact_id) {
        await api.put(`/v1/contacts/${encodeURIComponent(selectedConversation.contact_id)}/settings`, patchFields)
        await refreshWorkspace({ silent: true, fresh: true })
        setBanner(t('saved'))
        return
      }
      const currentOverrides = settings.web_settings?.reply?.user_overrides || {}
""",
    sentinel="selectedConversation?.contact_id",
)
replace(
    app,
    "              onTogglePin={togglePin}\n",
    "              onTogglePin={togglePin}\n",
)
replace(
    app,
    "              pinned={selectedConversation ? pinnedSet.has(selectedConversation.user_id) || Boolean(selectedConversation.pinned) : false}\n              onTogglePin={() => selectedConversation?.user_id && togglePin(selectedConversation.user_id)}\n",
    "              pinned={selectedConversation ? pinnedSet.has(selectedConversation.conversation_key) || Boolean(selectedConversation.pinned) : false}\n              onTogglePin={() => selectedConversation && togglePin(selectedConversation)}\n",
    sentinel="pinnedSet.has(selectedConversation.conversation_key)",
)
replace(
    app,
    "          const next = items.filter(i => i.pinned).map(i => i.user_id)\n",
    "          const next = items.filter(i => i.pinned).map(i => i.conversation_key || i.user_id)\n",
    sentinel="map(i => i.conversation_key || i.user_id)",
)

chat_list = "web/src/components/ChatList.jsx"
replace(
    chat_list,
    "  const isPinnedFn = userId => pinnedSet instanceof Set ? pinnedSet.has(userId) : Array.isArray(pinnedSet) ? pinnedSet.includes(userId) : Array.isArray(pinned) ? pinned.includes(userId) : false\n",
    "  const isPinnedFn = key => pinnedSet instanceof Set ? pinnedSet.has(key) : Array.isArray(pinnedSet) ? pinnedSet.includes(key) : Array.isArray(pinned) ? pinned.includes(key) : false\n",
)
replace(
    chat_list,
    "    const remark = selectedProfileMap?.[item.user_id]?.remark || ''\n",
    "    const remark = item.contact_profile?.remark || selectedProfileMap?.[item.user_id]?.remark || ''\n",
    sentinel="item.contact_profile?.remark",
)
replace(
    chat_list,
    "    const isPinned = item.pinned || isPinnedFn(item.user_id)\n",
    "    const isPinned = item.pinned || isPinnedFn(item.conversation_key || item.user_id)\n",
    sentinel="isPinnedFn(item.conversation_key",
)
replace(
    chat_list,
    "onPin={() => onTogglePin(item.user_id)}",
    "onPin={() => onTogglePin(item)}",
    sentinel="onTogglePin(item)",
)
replace(
    chat_list,
    "  const pinnedItems = conversations.filter(item => isPinnedFn(item.user_id) || item.pinned)\n  const normalItems = conversations.filter(item => !isPinnedFn(item.user_id) && !item.pinned)\n",
    "  const pinnedItems = conversations.filter(item => isPinnedFn(item.conversation_key || item.user_id) || item.pinned)\n  const normalItems = conversations.filter(item => !isPinnedFn(item.conversation_key || item.user_id) && !item.pinned)\n",
    sentinel="isPinnedFn(item.conversation_key || item.user_id)",
)

chat = "web/src/components/ChatPane.jsx"
replace(
    chat,
    "import { fmtClock } from '../format'\n",
    "import { fmtClock } from '../format'\nimport { formatChatDay, localDayKey } from '../dateTime'\n",
    sentinel="from '../dateTime'",
)
regex(
    chat,
    r'''function dayKey\(ts\) \{.*?\n\}\n\nfunction formatDay\(ts, t\) \{.*?\n\}\n''',
    '''function dayKey(ts) {
  return localDayKey(ts)
}

function formatDay(ts, t) {
  return formatChatDay(ts, t)
}
''',
    sentinel="return formatChatDay(ts, t)",
)
replace(
    chat,
    "  const deltaCursorRef = useRef(0)\n",
    "  const deltaCursorRef = useRef(0)\n  const standaloneCursorRef = useRef(null)\n",
    sentinel="standaloneCursorRef",
)
replace(
    chat,
    """    const endpoint = standalone && conversationId
      ? `/v1/conversations/${encodeURIComponent(conversationId)}/messages?limit=${pageSize}`
      : `/conversations/${encodeURIComponent(targetUserId)}?page=${p}&page_size=${pageSize}`
""",
    """    const cursor = standalone && appendOlder ? standaloneCursorRef.current : null
    const cursorQuery = cursor
      ? `&before_occurred_at=${encodeURIComponent(cursor.before_occurred_at)}&before_id=${encodeURIComponent(cursor.before_id)}`
      : ''
    const endpoint = standalone && conversationId
      ? `/v1/conversations/${encodeURIComponent(conversationId)}/messages?limit=${pageSize}${cursorQuery}`
      : `/conversations/${encodeURIComponent(targetUserId)}?page=${p}&page_size=${pageSize}`
""",
    sentinel="const cursorQuery = cursor",
)
replace(
    chat,
    "    setHasMore(standalone ? false : Boolean(res.has_more))\n",
    """    if (standalone) standaloneCursorRef.current = res.next_cursor || null
    setHasMore(Boolean(res.has_more))
""",
    sentinel="standaloneCursorRef.current = res.next_cursor",
)
replace(
    chat,
    "    deltaCursorRef.current = 0\n",
    "    deltaCursorRef.current = 0\n    standaloneCursorRef.current = null\n",
    sentinel="standaloneCursorRef.current = null",
)
replace(
    chat,
    "      const data = await onReply(target, sourceText, sendMode)\n",
    "      const data = await onReply(target, sourceText, sendMode, { idempotencyKey: tmpId })\n",
    sentinel="idempotencyKey: tmpId",
)
replace(
    chat,
    """       const finalLang = normalizeRewriteLanguage(data?.rewrite?.language)
       setMessages(prev => prev.map(m => m.message_id === tmpId ? {
""",
    """       const finalLang = normalizeRewriteLanguage(data?.rewrite?.language)
       const queued = Boolean(data?.queued) || data?.status === 'queued'
       setMessages(prev => prev.map(m => m.message_id === tmpId ? {
""",
    sentinel="const queued = Boolean(data?.queued)",
)
replace(
    chat,
    "         pending: false,\n         failed: false,\n         sent: true,\n",
    "         pending: queued,\n         failed: false,\n         sent: !queued,\n         status: data?.status || (queued ? 'queued' : 'sent'),\n",
    sentinel="status: data?.status ||",
)

write(
    "web/src/dateTime.js",
    """function dateParts(date, timeZone) {
  const formatter = new Intl.DateTimeFormat('en', {
    ...(timeZone ? { timeZone } : {}),
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  })
  const parts = Object.fromEntries(
    formatter.formatToParts(date)
      .filter(part => part.type !== 'literal')
      .map(part => [part.type, part.value]),
  )
  return `${parts.year}-${parts.month}-${parts.day}`
}

export function localDayKey(timestampSeconds, timeZone) {
  return dateParts(new Date(Number(timestampSeconds || 0) * 1000), timeZone)
}

export function formatChatDay(timestampSeconds, t, now = new Date(), timeZone) {
  const date = new Date(Number(timestampSeconds || 0) * 1000)
  const todayKey = dateParts(now, timeZone)
  const yesterday = new Date(now.getTime())
  yesterday.setDate(yesterday.getDate() - 1)
  const key = dateParts(date, timeZone)
  if (key === todayKey) return t('today')
  if (key === dateParts(yesterday, timeZone)) return t('yesterday')
  return date.toLocaleDateString(undefined, timeZone ? { timeZone } : undefined)
}
""",
)
write(
    "web/tests/dateTime.test.js",
    """import assert from 'node:assert/strict'
import test from 'node:test'
import { formatChatDay, localDayKey } from '../src/dateTime.js'

test('localDayKey respects Asia/Vientiane midnight instead of UTC', () => {
  const timestamp = Date.parse('2026-07-12T18:30:00Z') / 1000
  assert.equal(localDayKey(timestamp, 'Asia/Vientiane'), '2026-07-13')
  assert.equal(localDayKey(timestamp, 'UTC'), '2026-07-12')
})

test('formatChatDay resolves today and yesterday in the requested timezone', () => {
  const t = key => key
  const now = new Date('2026-07-13T12:00:00Z')
  assert.equal(formatChatDay(Date.parse('2026-07-13T01:00:00Z') / 1000, t, now, 'Asia/Vientiane'), 'today')
  assert.equal(formatChatDay(Date.parse('2026-07-12T01:00:00Z') / 1000, t, now, 'Asia/Vientiane'), 'yesterday')
})
""",
)

scheduler = "web/src/components/SchedulerCenterPage.jsx"
replace(scheduler, "api.get('/schedule')", "api.get('/v1/schedule')")
replace(scheduler, "api.post('/schedule'", "api.post('/v1/schedule'")
replace(scheduler, "api.delete(`/schedule/${id}`)", "api.delete(`/v1/schedule/${id}`)")

broadcast = "web/src/components/BroadcastCenterPage.jsx"
replace(broadcast, "api.get('/broadcast')", "api.get('/v1/broadcast')")
replace(broadcast, "api.post('/broadcast'", "api.post('/v1/broadcast'")

write(
    "web/vercel.json",
    """{
  "framework": "vite",
  "installCommand": "npm ci",
  "buildCommand": "npm run build",
  "outputDirectory": "dist",
  "rewrites": [
    { "source": "/(.*)", "destination": "/index.html" }
  ]
}
""",
)

# Remove superseded one-shot workflow files from the feature branch.
for stale in [
    ".github/workflows/frontend-reliability-patch.yml",
    ".github/workflows/python-autofix.yml",
    ".github/frontend-reliability-trigger",
    ".github/python-autofix-trigger",
]:
    path = ROOT / stale
    if path.exists():
        path.unlink()

# The running workflow already loaded its job definition. Restore the permanent CI.
write(
    ".github/workflows/ci.yml",
    """name: CI

on:
  push:
    branches: [main]
  pull_request:

permissions:
  contents: read

concurrency:
  group: ci-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  python:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: pip
      - name: Install
        run: python -m pip install --upgrade pip && python -m pip install -e . pytest httpx ruff
      - name: Ruff changed Python files
        shell: bash
        run: |
          base="origin/${GITHUB_BASE_REF:-main}"
          mapfile -t files < <(git diff --name-only --diff-filter=ACMR "$base...HEAD" -- '*.py')
          if [ "${#files[@]}" -eq 0 ]; then
            echo "No changed Python files"
            exit 0
          fi
          ruff check "${files[@]}"
          ruff format --check "${files[@]}"
      - name: Pytest
        run: pytest -q

  web:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: npm
          cache-dependency-path: web/package-lock.json
      - run: npm ci --prefix web
      - run: node --test web/tests/*.test.js
      - run: npm run build --prefix web

  bridge:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: npm
          cache-dependency-path: bridge/package-lock.json
      - run: npm ci --prefix bridge
      - run: npm test --prefix bridge
      - run: npm run lint --prefix bridge

  diff-quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - run: git diff --check origin/${{ github.base_ref || 'main' }}...HEAD
""",
)

# Self-delete after applying the patch.
Path(__file__).unlink()
