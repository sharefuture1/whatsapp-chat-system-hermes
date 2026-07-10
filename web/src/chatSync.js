export function mergeFreshMessages(serverItems, currentItems) {
  const sentByContent = new Map(
    currentItems
      .filter(item => item.role === 'assistant' && item.sent)
      .map(item => [`${item.role}:${item.content}`, item]),
  )
  const serverPlatformIds = new Set(serverItems.map(item => String(item.platform_message_id || '')).filter(Boolean))
  const serverKeys = new Set(serverItems.map(item => `${item.role}:${item.content}`))
  const mergedServer = serverItems.map(item => sentByContent.has(`${item.role}:${item.content}`) ? { ...item, sent: true } : item)
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
      return Boolean(
        request
        && request.sequence === sequence
        && request.userId === activeUserId
        && request.userId === userId,
      )
    },
    invalidate() {
      sequence += 1
      activeUserId = null
    },
  }
}
