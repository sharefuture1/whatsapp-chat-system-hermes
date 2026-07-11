export function mergeConversationPages(current, incoming, append) {
  if (!append) return incoming
  const merged = new Map(current.map(item => [item.conversation_key, item]))
  for (const item of incoming) merged.set(item.conversation_key, item)
  return [...merged.values()]
}

export function createRefreshCoordinator() {
  let generation = 0
  let inflight = null
  return {
    run(factory, commit, { fresh = false } = {}) {
      if (fresh) generation += 1
      const requestedGeneration = generation
      if (!fresh && inflight?.generation === requestedGeneration) return inflight.promise
      const promise = Promise.resolve().then(factory).then(result => {
        if (requestedGeneration === generation) commit(result)
        return result
      })
      inflight = { generation: requestedGeneration, promise }
      promise.then(
        () => { if (inflight?.promise === promise) inflight = null },
        () => { if (inflight?.promise === promise) inflight = null },
      )
      return promise
    },
  }
}
