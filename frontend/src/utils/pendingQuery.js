/**
 * Carries one query across the sign-in gate's navigation from the landing
 * page to Dashboard — sessionStorage rather than component state because
 * Search.jsx unmounts entirely when we navigate to /dashboard, taking any
 * local state with it. "Take" (read + clear in one call) rather than a
 * plain getter is what stops a stale query from resurrecting itself the
 * next time Dashboard mounts normally (e.g. via the sidebar).
 */
const KEY = 'projectmind.pendingQuery'

export function setPendingQuery(query) {
  try {
    sessionStorage.setItem(KEY, query)
  } catch {
    /* private mode, quota, storage disabled — the gate still works, the
       query just won't survive the redirect */
  }
}

export function takePendingQuery() {
  try {
    const value = sessionStorage.getItem(KEY)
    sessionStorage.removeItem(KEY)
    return value
  } catch {
    return null
  }
}

export function clearPendingQuery() {
  try {
    sessionStorage.removeItem(KEY)
  } catch {
    /* as above */
  }
}
