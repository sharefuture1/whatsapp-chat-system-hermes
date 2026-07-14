function dateParts(date, timeZone) {
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
