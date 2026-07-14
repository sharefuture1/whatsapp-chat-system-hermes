const LOCAL_TRANSLATION_FIELDS = ['translated', 'lang', 'translationError']
const SERVER_UPSERT_FIELDS = ['translated', 'lang', 'content', 'status', 'platform_message_id', 'media_metadata', 'message_type']
const LOCAL_DELIVERY_FIELDS = ['pending', 'failed', 'sent', 'local_only']

function hasOwn(item, field) {
  return Object.prototype.hasOwnProperty.call(item, field)
}

function stableMessageSort(items) {
  return items
    .map((item, index) => ({ item, index }))
    .sort((left, right) => {
      const timeDelta = Number(left.item.timestamp || 0) - Number(right.item.timestamp || 0)
      if (timeDelta) return timeDelta
      const leftId = Number(left.item.message_id)
      const rightId = Number(right.item.message_id)
      if (Number.isFinite(leftId) && Number.isFinite(rightId) && leftId !== rightId) return leftId - rightId
      return left.index - right.index
    })
    .map(entry => entry.item)
}

export function mergeNewMessages(currentItems, incomingItems) {
  return mergeNewMessagesWithStats(currentItems, incomingItems).items
}

export function mergeNewMessagesWithStats(currentItems, incomingItems) {
  if (!incomingItems.length) return { items: currentItems, newCount: 0 }
  const merged = currentItems.map(item => ({ ...item }))
  const indexById = new Map(merged.map((item, index) => [String(item.message_id), index]))
  let newCount = 0

  for (const incoming of incomingItems) {
    const id = String(incoming.message_id)
    const index = indexById.get(id)
    if (index === undefined) {
      indexById.set(id, merged.length)
      merged.push(incoming)
      newCount += 1
      continue
    }
    const local = merged[index]
    const next = { ...local }
    for (const field of SERVER_UPSERT_FIELDS) {
      if (hasOwn(incoming, field)) next[field] = incoming[field]
    }
    for (const [field, value] of Object.entries(incoming)) {
      if (!SERVER_UPSERT_FIELDS.includes(field) && !LOCAL_DELIVERY_FIELDS.includes(field)) next[field] = value
    }
    for (const field of LOCAL_DELIVERY_FIELDS) {
      if (!hasOwn(local, field) && hasOwn(incoming, field)) next[field] = incoming[field]
    }
    const serverStatus = String(incoming.status || '').toLowerCase()
    const reconciled = Boolean(incoming.platform_message_id) || ['sent', 'delivered', 'read', 'failed'].includes(serverStatus)
    if (reconciled) {
      next.pending = false
      next.local_only = false
    }
    if (['sent', 'delivered', 'read'].includes(serverStatus)) next.failed = false
    if (serverStatus === 'failed') next.failed = true
    merged[index] = next
  }
  return { items: stableMessageSort(merged), newCount }
}

export function mergeFreshMessages(serverItems, currentItems) {
  const currentById = new Map(currentItems.map(item => [String(item.message_id), item]))
  const sentByContent = new Map(
    currentItems
      .filter(item => item.role === 'assistant' && item.sent)
      .map(item => [`${item.role}:${item.content}`, item]),
  )
  const serverPlatformIds = new Set(serverItems.map(item => String(item.platform_message_id || '')).filter(Boolean))
  const serverKeys = new Set(serverItems.map(item => `${item.role}:${item.content}`))
  const mergedServer = serverItems.map(item => {
    const local = currentById.get(String(item.message_id))
    const merged = sentByContent.has(`${item.role}:${item.content}`) ? { ...item, sent: true } : { ...item }
    if (local) {
      const hasValidTranslated = hasOwn(item, 'translated') && Boolean(item.translated)
      const hasValidLang = hasOwn(item, 'lang') && Boolean(item.lang) && item.lang !== 'Unknown'
      if (!hasValidTranslated && !hasValidLang) {
        for (const field of LOCAL_TRANSLATION_FIELDS) {
          if (hasOwn(local, field)) merged[field] = local[field]
          else delete merged[field]
        }
      }
    }
    return merged
  })
  const unresolvedLocal = currentItems.filter(item => {
    const id = String(item.message_id || '')
    if (!id.startsWith('tmp-') && !item.local_only) return false
    if (!item.pending && !item.failed && !item.local_only) return false
    const platformId = String(item.platform_message_id || '')
    if (platformId && serverPlatformIds.has(platformId)) return false
    return !serverKeys.has(`${item.role}:${item.content}`)
  })
  return [...mergedServer, ...unresolvedLocal]
}

export function commitMessagesUpdate(messagesRef, setMessages, updater) {
  const next = updater(messagesRef.current)
  messagesRef.current = next
  setMessages(next)
  return next
}

export function isTranslationRetryEligible(message, now = Date.now()) {
  return !message?.translationRetryAfter || Number(message.translationRetryAfter) <= now
}

export function nextTranslationRetryDelay(messages, now = Date.now()) {
  const future = messages
    .map(message => Number(message?.translationRetryAfter || 0))
    .filter(retryAfter => retryAfter > now)
  return future.length ? Math.min(...future) - now : 0
}

export function createConversationRequestTracker() {
  let sequence = 0
  let activeUserId = null

  return {
    activate(userId) {
      sequence += 1
      activeUserId = userId || null
    },
    begin(userId) {
      sequence += 1
      return { sequence, userId }
    },
    isActive(userId) {
      return Boolean(userId && userId === activeUserId)
    },
    isCurrent(request, userId) {
      return Boolean(request && request.sequence === sequence && request.userId === activeUserId && request.userId === userId)
    },
    invalidate() {
      sequence += 1
      activeUserId = null
    },
  }
}

export function createConversationDeltaScheduler() {
  let generation = 0
  let activeUserId = null
  let running = false
  let runningUserId = null
  let rerun = false
  let queued = null
  let activePromise = null
  let latestRun = null

  const start = (userId, run) => {
    latestRun = run
    const runGeneration = generation
    const context = {
      userId,
      isCurrent: () => generation === runGeneration && activeUserId === userId,
    }
    running = true
    runningUserId = userId
    activePromise = (async () => {
      do {
        rerun = false
        const currentRun = latestRun
        await currentRun(context)
      } while (rerun && context.isCurrent())
    })().finally(() => {
      running = false
      runningUserId = null
      activePromise = null
      const next = queued
      queued = null
      if (next && next.userId === activeUserId) start(next.userId, next.run)
    })
    return activePromise
  }

  return {
    activate(userId) {
      generation += 1
      activeUserId = userId || null
      rerun = false
      queued = null
    },
    invalidate() {
      generation += 1
      activeUserId = null
      rerun = false
      queued = null
    },
    trigger(userId, run) {
      if (!userId || userId !== activeUserId) return Promise.resolve()
      if (running) {
        if (runningUserId === userId) {
          rerun = true
          latestRun = run
        } else {
          queued = { userId, run }
        }
        return activePromise
      }
      return start(userId, run)
    },
  }
}
