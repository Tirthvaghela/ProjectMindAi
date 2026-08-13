import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import api, { clearAuthToken, getAuthToken, rotateDeviceId, setAuthToken } from '../services/api'

/**
 * Auth state as React context, not a per-component hook like useFavorites.
 *
 * Favourites are consulted locally per list and tolerate independent copies
 * drifting slightly. Auth doesn't: signing in on the Account page has to be
 * visible in the nav immediately, and every page that gates on `user` needs
 * the same answer at the same time. One provider, one source of truth.
 */
const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    if (!getAuthToken()) {
      setUser(null)
      setLoading(false)
      return
    }
    try {
      const { data } = await api.me()
      setUser(data)
    } catch {
      // Token is missing, expired, or revoked server-side — same outcome
      // either way: forget it and treat this browser as signed out.
      clearAuthToken()
      setUser(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const signup = async (email, password, name) => {
    const res = await api.signup(email, password, name)
    setAuthToken(res.token)
    setUser(res.data)
    return res.data
  }

  const login = async (email, password) => {
    const res = await api.login(email, password)
    setAuthToken(res.token)
    setUser(res.data)
    return res.data
  }

  const logout = async () => {
    try {
      await api.logout()
    } catch {
      /* Token may already be invalid server-side — clearing it locally still succeeds. */
    }
    clearAuthToken()
    setUser(null)
    // A signed-out browser starts a fresh anonymous identity rather than
    // continuing to carry this account's device-scoped favourites/history/
    // conversations — see rotateDeviceId's own docstring for why this
    // matters on a shared computer.
    rotateDeviceId()
  }

  const updateProfile = async (payload) => {
    const res = await api.updateProfile(payload)
    if (res.token) setAuthToken(res.token) // only present when the password changed
    setUser(res.data)
    return res.data
  }

  return (
    <AuthContext.Provider value={{ user, loading, signup, login, logout, updateProfile, refresh }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within <AuthProvider>')
  return ctx
}

export default useAuth
