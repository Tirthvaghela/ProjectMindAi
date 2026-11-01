/**
 * Which failed requests mean "you can no longer see this" (as opposed to a temporary problem).
 *
 * services/api.js puts the HTTP status on every API error (`error.status`); it is null for
 * network failures and timeouts, which are therefore never treated as lost access.
 *
 * The sub-team endpoints (backend/routes/subteams.py, teams/subteams.py) answer:
 *   404  not on the parent team, not on the sub-team (non-owner), or it no longer exists -
 *        deliberately the same answer so a caller learns nothing about which
 *   401  the session is gone or expired
 *   403  on the chat only: the parent owner who is not a member of that sub-team
 * 5xx, 429, 400 and network errors say nothing about access.
 */

/** A read of a sub-team resource (its details, tasks or role suggestions) that can no longer succeed. */
export function isResourceGone(error) {
  return error?.status === 404 || error?.status === 401
}

/** A read or send on a sub-team's chat that is no longer allowed. */
export function isAccessLost(error) {
  return isResourceGone(error) || error?.status === 403
}
