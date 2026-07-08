export function fmtTime(ts) {
  if (!ts) return '-'
  const d = new Date(ts * 1000)
  try {
    return d.toLocaleString()
  } catch {
    return d.toISOString()
  }
}

export function fmtRelative(ts) {
  if (!ts) return ''
  const now = Date.now()
  const then = ts * 1000
  const diff = Math.max(0, now - then)
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h`
  const days = Math.floor(hours / 24)
  return `${days}d`
}
