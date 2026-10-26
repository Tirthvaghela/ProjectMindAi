import { useCallback, useEffect, useState } from 'react'
import api from '../services/api'
import useAuth from './useAuth.jsx'

export const PROFILE_CHANGED = 'projectmind:profile-changed'

/** Tell every mounted useProfile() (the nudge banner, the profile page) that
 * the stored profile just changed, so they refetch instead of showing stale
 * completion state. */
export function announceProfileChanged() {
  window.dispatchEvent(new Event(PROFILE_CHANGED))
}

/**
 * The signed-in account's learner profile.
 *
 * `status` is 'idle' (signed out / not asked), 'loading', 'ready' or 'error'.
 * Nothing is fetched while signed out — the endpoint would 401 — and a failed
 * load leaves `profile` null so callers can simply render nothing rather than
 * guess at completion.
 */
export default function useProfile() {
  const { user, loading: authLoading } = useAuth()
  const [profile, setProfile] = useState(null)
  const [status, setStatus] = useState('idle')
  const [error, setError] = useState(null)

  const reload = useCallback(async () => {
    if (!user) return
    setStatus((current) => (current === 'ready' ? current : 'loading'))
    try {
      const { data } = await api.learnerProfile()
      setProfile(data)
      setError(null)
      setStatus('ready')
    } catch (err) {
      setError(err.message)
      setStatus('error')
    }
  }, [user])

  useEffect(() => {
    if (authLoading) return
    if (!user) {
      setProfile(null)
      setStatus('idle')
      return
    }
    reload()
    window.addEventListener(PROFILE_CHANGED, reload)
    return () => window.removeEventListener(PROFILE_CHANGED, reload)
  }, [user, authLoading, reload])

  return { profile, status, error, reload }
}
