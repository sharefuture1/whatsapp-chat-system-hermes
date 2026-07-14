const PREFIX = 'whatsapp-standalone-cache:v1:'
const MAX_MESSAGES = 300
const MAX_CONVERSATIONS = 30
const MESSAGE_TTL_MS = 5 * 60 * 1000
const TRANSLATION_TTL_MS = 30 * 24 * 60 * 60 * 1000

function read(key, fallback = null) {
  try {
    const raw = localStorage.getItem(`${PREFIX}${key}`)
    return raw ? JSON.parse(raw) : fallback
  } catch {
    return fallback
  }
}

function write(key, value) {
  try {
    localStorage.setItem(`${PREFIX}${key}`, JSON.stringify(value))
  } catch {
    // Quota errors must never break chat rendering.
  }
}

function safeId(value) {
  return encodeURIComponent(String(value || '')).slice(0, 180)
}

export function loadConversationCache(conversationId) {
  if (!conversationId) return null
  const item = read(`conversation:${safeId(conversationId)}`)
  if (!item || !Array.isArray(item.messages)) return null
  return item
}

export function saveConversationCache(conversationId, messages, meta = {}) {
  if (!conversationId || !Array.isArray(messages)) return
  const existing = loadConversationCache(conversationId)
  const merged = new Map((existing?.messages || []).map(item => [String(item.message_id), item]))
  for (const message of messages.slice(-MAX_MESSAGES)) {
    if (message?.message_id != null) merged.set(String(message.message_id), message)
  }
  const next = Array.from(merged.values()).slice(-MAX_MESSAGES)
  write(`conversation:${safeId(conversationId)}`, {
    messages: next,
    ...meta,
    savedAt: Date.now(),
  })
}

export function isConversationCacheFresh(item, now = Date.now()) {
  return Boolean(item?.savedAt && now - Number(item.savedAt) < MESSAGE_TTL_MS)
}

export function loadTranslationCache(messageId, content) {
  if (!messageId || !content) return null
  const key = `translation:${safeId(messageId)}:${safeId(content).slice(0, 80)}`
  const item = read(key)
  if (!item || Date.now() - Number(item.savedAt || 0) > TRANSLATION_TTL_MS) return null
  return item.value || null
}

export function saveTranslationCache(messageId, content, value) {
  if (!messageId || !content || !value) return
  const key = `translation:${safeId(messageId)}:${safeId(content).slice(0, 80)}`
  write(key, { value, savedAt: Date.now() })
}

export function clearConversationCache(conversationId) {
  if (!conversationId) return
  try { localStorage.removeItem(`${PREFIX}conversation:${safeId(conversationId)}`) } catch {}
}

export const CHAT_CACHE_LIMITS = { MAX_MESSAGES, MAX_CONVERSATIONS }
