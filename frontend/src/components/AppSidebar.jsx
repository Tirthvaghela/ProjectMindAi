import { useEffect, useState } from 'react'
import { Link, NavLink, useSearchParams } from 'react-router-dom'
import useAuth from '../hooks/useAuth.jsx'
import api from '../services/api'

const MODULES = [
  { icon: 'auto_awesome', label: 'New Idea', to: '/ideate' },
  { icon: 'badge', label: 'Résumé Match', to: '/resume-match' },
  { icon: 'fingerprint', label: 'Idea Check', to: '/uniqueness' },
  { icon: 'groups', label: 'Teams', to: '/teams' },
  { icon: 'bookmark', label: 'Favourites', to: '/favorites' },
]

/**
 * The app's permanent chrome — a ChatGPT-style shell. Dashboard.jsx is the
 * one home now (chat + project search fused into a single thread, see its
 * own header comment), so "Recents" here is conversation history, not a
 * separate search log.
 */
export default function AppSidebar({ open = false, onClose }) {
  const { user, loading: authLoading } = useAuth()
  const [searchParams] = useSearchParams()
  const activeConversation = searchParams.get('c')
  const [conversations, setConversations] = useState([])
  const [status, setStatus] = useState('loading')

  const load = () => {
    api
      .listConversations()
      .then((res) => {
        setConversations(res.data)
        setStatus('done')
      })
      .catch(() => setStatus('error'))
  }

  // Conversations are anonymous device-scoped data, but sending a *new*
  // message now requires an account (see AuthGateModal) — so a signed-out
  // visitor's device may still carry old history from before that gate
  // existed. Showing it here would make the whole shell look like an
  // active session even though it isn't, which is exactly the contradiction
  // Teams (correctly account-gated) then exposes. `user` is the same source
  // of truth Teams/Dashboard/TeamRoom all check, so this list only loads
  // once it's known who — if anyone — is signed in.
  useEffect(() => {
    if (authLoading) return
    if (!user) {
      setConversations([])
      setStatus('signed-out')
      return
    }
    load()
    // Conversations change from turns sent inside Dashboard's thread, which
    // don't touch the URL. A 20s poll (same pattern as NotificationsBell)
    // keeps this eventually correct; the event listener is what makes a
    // *new* chat you just sent show up immediately instead of waiting on it.
    const interval = setInterval(load, 20000)
    window.addEventListener('projectmind:conversations-changed', load)
    return () => {
      clearInterval(interval)
      window.removeEventListener('projectmind:conversations-changed', load)
    }
  }, [user, authLoading])

  const deleteConversation = async (event, id) => {
    event.preventDefault()
    event.stopPropagation()
    try {
      await api.deleteConversation(id)
      setConversations((cs) => cs.filter((c) => c.conversation_id !== id))
    } catch {
      /* Next poll reconciles either way. */
    }
  }

  return (
    <nav
      className={`fixed inset-y-0 left-0 z-50 flex h-full w-64 shrink-0 flex-col transition-transform duration-200 lg:static lg:z-40 lg:translate-x-0 ${open ? 'translate-x-0' : '-translate-x-full'}`}
      style={{ background: 'var(--surface-container-low)', borderRight: '1px solid var(--border-technical)' }}
    >
      <div className="p-6" style={{ borderBottom: '1px solid var(--border-technical)' }}>
        <div className="mb-6 flex items-center justify-between">
          <Link to="/dashboard" className="flex items-center gap-3">
            <span className="material-symbols-outlined" style={{ color: 'var(--primary)', fontSize: 26 }}>
              hub
            </span>
            <h1 className="t-headline-md" style={{ color: 'var(--primary)', fontSize: 18 }}>
              ProjectMind AI
            </h1>
          </Link>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close menu"
            className="grid h-8 w-8 shrink-0 place-items-center transition hover:bg-white/5 lg:hidden"
            style={{ color: 'var(--outline)', borderRadius: 6 }}
          >
            <span className="material-symbols-outlined" style={{ fontSize: 18 }}>
              close
            </span>
          </button>
        </div>
        <Link
          to="/dashboard"
          className="t-label-caps flex w-full items-center justify-center gap-2 px-4 py-3 transition hover:opacity-85"
          style={{ background: 'var(--primary)', color: 'var(--on-primary)', borderRadius: 8 }}
        >
          <span className="material-symbols-outlined" style={{ fontSize: 16 }}>
            add
          </span>
          New chat
        </Link>
      </div>

      <div className="mb-2 mt-8 px-4">
        <span className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>
          Workspace
        </span>
      </div>
      <ul className="space-y-1">
        {MODULES.map((mod) => (
          <li key={mod.to}>
            <NavLink
              to={mod.to}
              end={mod.to === '/dashboard'}
              className={({ isActive }) => `flex items-center gap-3 rounded-md px-4 py-2 transition hover:bg-white/5${isActive ? ' nav-item-active' : ''}`}
              style={({ isActive }) => ({
                color: isActive ? 'var(--primary)' : 'var(--on-surface-variant)',
                background: isActive ? 'var(--surface-container-high)' : 'transparent',
              })}
            >
              <span className="material-symbols-outlined" style={{ fontSize: 16 }}>
                {mod.icon}
              </span>
              <span className="t-label-mono">{mod.label}</span>
            </NavLink>
          </li>
        ))}
      </ul>
      
      <div className="flex-1 overflow-y-auto px-2 py-4">
        <div className="mb-2 px-4">
          <span className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>
            Recent Conversations
          </span>
        </div>
        {status === 'loading' && (
          <p className="t-label-mono px-4 text-xs" style={{ color: 'var(--outline)' }}>
            Loading…
          </p>
        )}
        {status === 'signed-out' && (
          <p className="t-label-mono px-4 text-xs" style={{ color: 'var(--outline)' }}>
            Sign in to see your chat history.
          </p>
        )}
        {status === 'error' && (
          <div className="px-4">
            <p className="t-label-mono text-xs" style={{ color: '#ffb4ab' }}>
              Couldn't load your conversations.
            </p>
            <button
              type="button"
              onClick={load}
              className="t-label-mono mt-1 text-xs transition hover:opacity-75"
              style={{ color: 'var(--outline)', textDecoration: 'underline' }}
            >
              Try again
            </button>
          </div>
        )}
        {status === 'done' && conversations.length === 0 && (
          <p className="t-label-mono px-4 text-xs" style={{ color: 'var(--outline)' }}>
            No conversations yet.
          </p>
        )}
        <ul className="space-y-1">
          {conversations.map((c) => {
            const active = c.conversation_id === activeConversation
            return (
              <li key={c.conversation_id} className="group relative">
                <Link
                  to={`/dashboard?c=${c.conversation_id}`}
                  className={`flex items-center gap-3 rounded-md py-2 pl-4 pr-8 transition hover:bg-white/5${active ? ' nav-item-active' : ''}`}
                  style={{ color: active ? 'var(--primary)' : 'var(--on-surface-variant)', background: active ? 'var(--surface-container-high)' : 'transparent' }}
                >
                  <span className="material-symbols-outlined shrink-0" style={{ fontSize: 16, color: active ? 'var(--primary)' : 'var(--outline)' }}>
                    chat_bubble
                  </span>
                  <span className="t-label-mono truncate">{c.title}</span>
                </Link>
                <button
                  onClick={(e) => deleteConversation(e, c.conversation_id)}
                  aria-label={`Delete "${c.title}"`}
                  className="absolute right-1.5 top-1.5 p-1 opacity-0 transition hover:bg-white/10 group-hover:opacity-100"
                  style={{ color: 'var(--outline)', borderRadius: 6 }}
                >
                  <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 7h12M9 7V5a1 1 0 011-1h4a1 1 0 011 1v2m2 0l-.7 12.1a1 1 0 01-1 .9H7.7a1 1 0 01-1-.9L6 7h12z" />
                  </svg>
                </button>
              </li>
            )
          })}
        </ul>


      </div>

      <div className="p-4" style={{ borderTop: '1px solid var(--border-technical)' }}>
        <Link
          to="/account"
          className="flex items-center gap-3 rounded-md px-4 py-2 transition hover:bg-white/5"
          style={{ color: 'var(--on-surface-variant)' }}
        >
          <span className="material-symbols-outlined" style={{ fontSize: 16 }}>
            settings
          </span>
          <span className="t-label-mono">Settings</span>
        </Link>

        {user ? (
          <div className="mt-2 flex items-center gap-3 rounded-md px-4 py-2">
            <div
              className="grid h-8 w-8 shrink-0 place-items-center rounded-full"
              style={{ background: 'var(--surface-container-highest)', border: '1px solid var(--border-technical)' }}
            >
              <span className="material-symbols-outlined" style={{ fontSize: 16, color: 'var(--on-surface-variant)' }}>
                person
              </span>
            </div>
            <div className="min-w-0 flex-1">
              <p className="t-label-mono truncate" style={{ color: 'var(--primary)' }}>
                {user.name}
              </p>
              <p className="truncate" style={{ color: 'var(--outline)', fontSize: 10 }}>
                {user.email}
              </p>
            </div>
          </div>
        ) : (
          <Link
            to="/account"
            className="t-label-caps mt-4 flex items-center justify-center px-4 py-2 transition hover:opacity-85"
            style={{ background: 'var(--primary)', color: 'var(--on-primary)', borderRadius: 8 }}
          >
            Sign in
          </Link>
        )}
      </div>
    </nav>
  )
}
