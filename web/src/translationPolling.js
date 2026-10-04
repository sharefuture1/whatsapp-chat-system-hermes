function abortError() {
  return new DOMException('Translation polling aborted', 'AbortError')
}

function pauseWithAbort(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(abortError())
    const onAbort = () => {
      clearTimeout(timer)
      signal?.removeEventListener('abort', onAbort)
      reject(abortError())
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort)
      resolve()
    }, ms)
    signal?.addEventListener('abort', onAbort, { once: true })
  })
}

// Poll the batch state, not stale cached messages; stop on terminal status.
// A long provider request remains pending and may be checked again later.
export async function waitForTranslationBatch({ check, signal, pause = pauseWithAbort, attempts = 8 }) {
  let result = { status: 'pending' }
  for (let attempt = 0; attempt < attempts; attempt++) {
    if (signal?.aborted) throw abortError()
    await pause(Math.min(4000, 500 * (attempt + 1)), signal)
    if (signal?.aborted) throw abortError()
    result = await check()
    if (['completed', 'failed', 'dead', 'cancelled'].includes(result?.status)) return result
  }
  return result
}
