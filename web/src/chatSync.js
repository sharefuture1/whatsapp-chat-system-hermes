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
