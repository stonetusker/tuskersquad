/**
 * time.js — human-readable timestamp utilities for TuskerSquad UI
 *
 * All timestamps from the API are UTC ISO strings without a timezone suffix
 * (e.g. "2025-03-15T06:55:54"). We append "Z" before parsing so the browser
 * treats them as UTC and converts correctly to local time.
 */

/**
 * Parse an ISO string that may or may not have a "Z" / offset suffix.
 * The TuskerSquad API uses datetime.utcnow().isoformat() which produces
 * strings like "2025-03-15T06:55:54.123456" — no "Z". We add it so
 * the browser parses as UTC, not local time.
 */
function parseUTC(isoString) {
  if (!isoString) return null
  const s = String(isoString)
  // Already has timezone info
  if (s.endsWith('Z') || s.includes('+') || /\d{2}:\d{2}$/.test(s.slice(-6))) {
    return new Date(s)
  }
  // No timezone — assume UTC
  return new Date(s + 'Z')
}

/**
 * formatRelative — used for workflow created_at in the Recent Reviews list.
 *
 * Returns:
 *   "Just now"          — less than 60 seconds ago
 *   "5 minutes ago"     — less than 60 minutes ago
 *   "2 hours ago"       — less than 24 hours ago
 *   "Today 14:32"       — same calendar day, older than 1 hour
 *   "Yesterday 09:15"   — previous calendar day
 *   "Mar 15, 09:15"     — anything older
 */
export function formatRelative(isoString) {
  const date = parseUTC(isoString)
  if (!date || isNaN(date)) return '—'

  const now = new Date()
  const diffMs = now - date
  const diffSec = Math.floor(diffMs / 1000)
  const diffMin = Math.floor(diffSec / 60)
  const diffHrs = Math.floor(diffMin / 60)

  if (diffSec < 60)  return 'Just now'
  if (diffMin < 60)  return `${diffMin} minute${diffMin !== 1 ? 's' : ''} ago`
  if (diffHrs < 2)   return `${diffHrs} hour ago`
  if (diffHrs < 24) {
    // Check if still same calendar day
    const todayStr = now.toDateString()
    const dateStr  = date.toDateString()
    if (todayStr === dateStr) {
      return 'Today ' + date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    }
    return `${diffHrs} hours ago`
  }

  // Check yesterday
  const yesterday = new Date(now)
  yesterday.setDate(yesterday.getDate() - 1)
  if (date.toDateString() === yesterday.toDateString()) {
    return 'Yesterday ' + date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  }

  // Older — show "Mar 15, 14:32"
  return date.toLocaleDateString([], { month: 'short', day: 'numeric' }) +
    ', ' + date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

/**
 * formatClock — used for agent started_at / completed_at in timeline/reasoning views.
 *
 * Shows wall-clock time (HH:MM:SS) — appropriate when the user is looking at
 * a specific workflow and wants to know exactly when each agent ran.
 * Full datetime is available as a tooltip title attribute.
 */
export function formatClock(isoString) {
  const date = parseUTC(isoString)
  if (!date || isNaN(date)) return '—'
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

/**
 * formatDateTime — used for workflow detail header (created_at) and LLM log timestamps.
 *
 * Returns "Mar 15 2025, 14:32:05" — unambiguous full datetime.
 */
export function formatDateTime(isoString) {
  const date = parseUTC(isoString)
  if (!date || isNaN(date)) return '—'
  return date.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' }) +
    ', ' + date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

/**
 * fullTooltip — ISO string reformatted for a title="" tooltip attribute.
 * Gives the full unambiguous datetime when user hovers any formatted timestamp.
 */
export function fullTooltip(isoString) {
  const date = parseUTC(isoString)
  if (!date || isNaN(date)) return ''
  return date.toLocaleString([], {
    weekday: 'short', year: 'numeric', month: 'short',
    day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit'
  })
}
