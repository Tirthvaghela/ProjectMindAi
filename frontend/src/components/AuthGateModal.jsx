import { useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { AnimatePresence, motion } from 'framer-motion'
import useAuth from '../hooks/useAuth.jsx'
import './landing/landing.css'
import { useFocusTrap } from './useFocusTrap'

/**
 * The sign-in prompt that interrupts search/chat for a signed-out visitor —
 * a portal (not inline JSX) so it sits above everything regardless of which
 * page triggered it, blurred backdrop and all. `onAuthenticated` fires with
 * no arguments; the caller already knows what it was waiting to do (send a
 * message, run a search) and does it itself rather than this modal trying
 * to guess.
 */
export default function AuthGateModal({ open, onClose, onAuthenticated, message }) {
  const { signup, login } = useAuth()
  const [mode, setMode] = useState('login')
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const dialogRef = useRef(null)
  const titleId = useId()
  useFocusTrap(dialogRef, open, onClose)

  if (!open) return null

  const submit = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      if (mode === 'signup') await signup(email, password, name)
      else await login(email, password)
      onAuthenticated()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return createPortal(
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.15 }}
        className="landing-mono fixed inset-0 z-[100] flex items-center justify-center p-6"
        style={{ background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(10px)', WebkitBackdropFilter: 'blur(10px)' }}
        onClick={onClose}
      >
        <motion.div
          ref={dialogRef}
          role="dialog"
          aria-modal="true"
          aria-labelledby={titleId}
          tabIndex={-1}
          initial={{ opacity: 0, y: 12, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 12, scale: 0.98 }}
          transition={{ duration: 0.2 }}
          onClick={(event) => event.stopPropagation()}
          className="glass-panel relative w-full max-w-sm p-7"
          style={{ borderRadius: 12, outline: 'none' }}
        >
          <button
            onClick={onClose}
            aria-label="Close"
            className="absolute right-4 top-4 grid h-8 w-8 place-items-center transition hover:bg-white/5"
            style={{ color: 'var(--outline)', borderRadius: 6 }}
          >
            <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path strokeLinecap="round" d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>

          <span
            className="t-label-caps inline-block px-3 py-1"
            style={{ border: '1px solid var(--border-technical)', background: 'var(--surface-glass)', color: 'var(--on-surface-variant)', borderRadius: 999 }}
          >
            Account access
          </span>
          <h2 id={titleId} className="t-headline-lg mt-5" style={{ color: 'var(--primary)' }}>
            {mode === 'login' ? 'Sign in to continue' : 'Create an account'}
          </h2>
          <p className="t-body-md mt-3" style={{ color: 'var(--on-surface-variant)', fontSize: 13 }}>
            {message || 'Sign in to search and chat with ProjectMind.'}
          </p>

          <form onSubmit={submit} className="mt-6 space-y-4">
            {mode === 'signup' && (
              <label className="block">
                <span className="t-label-caps mb-1.5 block" style={{ color: 'var(--outline)', fontSize: 10 }}>Name</span>
                <input value={name} onChange={(e) => setName(e.target.value)} required autoFocus maxLength={80} className="gm-input w-full px-4 py-3 text-sm" />
              </label>
            )}
            <label className="block">
              <span className="t-label-caps mb-1.5 block" style={{ color: 'var(--outline)', fontSize: 10 }}>Email</span>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoFocus={mode === 'login'}
                className="gm-input w-full px-4 py-3 text-sm"
              />
            </label>
            <label className="block">
              <span className="t-label-caps mb-1.5 block" style={{ color: 'var(--outline)', fontSize: 10 }}>Password</span>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={mode === 'signup' ? 8 : undefined}
                className="gm-input w-full px-4 py-3 text-sm"
              />
            </label>

            {error && <p className="t-body-md" style={{ color: '#ffb4ab', fontSize: 13 }}>{error}</p>}

            <button type="submit" disabled={busy} className="btn-primary t-label-caps w-full px-4 py-3">
              {busy ? 'One moment…' : mode === 'login' ? 'Sign in' : 'Create account'}
            </button>

            <button
              type="button"
              onClick={() => {
                setMode((m) => (m === 'login' ? 'signup' : 'login'))
                setError(null)
              }}
              className="t-label-mono w-full text-center transition hover:opacity-75"
              style={{ color: 'var(--outline)', fontSize: 12 }}
            >
              {mode === 'login' ? "Don't have an account? Create one" : 'Already have an account? Sign in'}
            </button>
          </form>
        </motion.div>
      </motion.div>
    </AnimatePresence>,
    document.body,
  )
}
