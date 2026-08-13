/**
 * The backend serializes timestamps with Python's datetime.isoformat(),
 * which differs by field: some are naive (no timezone suffix), some are
 * timezone-aware (already end in "+00:00"). Blindly appending "Z" to an
 * already-aware string produces an unparseable "...+00:00Z" that silently
 * renders as "Invalid Date" — this checks for an existing offset first.
 */
function parseServerDate(iso) {
  const hasTimezone = /(Z|[+-]\d{2}:\d{2})$/.test(iso)
  return new Date(hasTimezone ? iso : `${iso}Z`)
}

export function formatRelative(iso) {
  const date = parseServerDate(iso)
  const minutesAgo = Math.floor((Date.now() - date.getTime()) / 60000)
  if (minutesAgo < 1) return 'just now'
  if (minutesAgo < 60) return `${minutesAgo}m ago`
  if (minutesAgo < 1440) return `${Math.floor(minutesAgo / 60)}h ago`
  return date.toLocaleDateString()
}

export function formatClockTime(iso) {
  return parseServerDate(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

export function formatDate(iso) {
  return parseServerDate(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}
