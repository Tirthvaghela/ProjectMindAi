import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion, useReducedMotion } from 'framer-motion'
import useAuth from '../hooks/useAuth.jsx'
import api from '../services/api'

// What an account actually unlocks in this app (see nlp/chat_tools.py,
// routes/teams.py) — real capabilities, not marketing filler, matching the
// landing page's own rule of only naming things that are actually wired up.
const CAPABILITIES = [
  { icon: 'forum', label: 'AI Chat' },
  { icon: 'travel_explore', label: 'Project Discovery' },
  { icon: 'fingerprint', label: 'Idea Validation' },
  { icon: 'route', label: 'Project Planning' },
]

// The same request→plan pipeline the landing page's own pipeline diagrams
// describe (see LandingHero.jsx: DISCOVER_FLOW/IDEATE_FLOW), condensed to
// one shared path — a technical diagram, not a second piece of marketing copy.
const SYSTEM_FLOW = ['User Request', 'AI Reasoning', 'Hybrid Retrieval', 'Validation', 'Project Plan']

// Reused directly from the landing page's own STATS/trust-metrics band
// (LandingHero.jsx) — same {value, label} shape as STATS there, no new
// numbers invented for this screen.
const SYSTEM_METRICS = [
  { value: '500+', label: 'Projects indexed' },
  { value: '384-D', label: 'Embedding dimensions' },
  { value: 'Hybrid', label: 'Semantic + keyword search' },
  { value: 'AI', label: 'Project planning' },
]

const JOURNEY = ['Landing Page', 'ProjectMind System', 'Account Access', 'Your Workspace']

/** One faint background node — decorative only, never legible enough to
 * compete with real content (see AccountBackdrop). */
function BackdropNode({ left, top, opacity = 0.12 }) {
  return <span className="absolute h-1 w-1 rounded-full" style={{ left, top, background: `rgba(255,255,255,${opacity})` }} />
}
function BackdropLine({ left, top, width, rotate = 0, opacity = 0.05, className = '' }) {
  return (
    <span
      className={`absolute h-px ${className}`}
      style={{ left, top, width, background: `rgba(255,255,255,${opacity})`, transformOrigin: 'left center', transform: `rotate(${rotate}deg)` }}
    />
  )
}
function BackdropLabel({ left, top, children, className = '' }) {
  return (
    <span
      className={`absolute whitespace-nowrap ${className}`}
      style={{ left, top, fontFamily: "'JetBrains Mono', monospace", fontSize: 9, letterSpacing: '0.08em', color: 'rgba(255,255,255,0.07)' }}
    >
      {children}
    </span>
  )
}
function BackdropRule({ left, top, width }) {
  return <span className="absolute h-px" style={{ left, top, width, background: 'rgba(255,255,255,0.04)' }} />
}

/**
 * Ambient technical texture behind the whole page — faint connection lines,
 * tiny nodes and near-invisible readout labels scattered in the margins,
 * deliberately never inside the content columns. Percentage-positioned
 * (not one scaled SVG) so nothing distorts across viewport widths; every
 * value here is decorative, not real telemetry, unlike the health-derived
 * "Workspace status" row on the card below.
 *
 * `showConnector` adds one deliberately less-faint diagonal line bridging
 * the left column's system diagram toward the auth card — the one backdrop
 * element that's meant to be *noticed* (if only barely) rather than purely
 * ambient, so it only renders on the two-column signed-out layout where
 * there's an actual diagram on one side and a card on the other to bridge.
 */
function AccountBackdrop({ showConnector = false }) {
  return (
    <div className="pointer-events-none absolute inset-0 z-0 overflow-hidden" aria-hidden="true">
      <BackdropNode left="3%" top="14%" />
      <BackdropNode left="3.6%" top="24%" opacity={0.08} />
      <BackdropLine left="3%" top="14%" width="70px" rotate={78} />
      <BackdropLabel left="4.6%" top="12.5%">NODE_04</BackdropLabel>

      <BackdropNode left="96%" top="9%" />
      <BackdropNode left="94.5%" top="18%" opacity={0.08} />
      <BackdropLine left="96%" top="9%" width="55px" rotate={100} />
      <BackdropLabel left="90.5%" top="7%">SYS::OK</BackdropLabel>

      <BackdropNode left="95%" top="66%" opacity={0.1} />
      <BackdropNode left="97.5%" top="76%" opacity={0.07} />
      <BackdropLine left="95%" top="66%" width="65px" rotate={65} />
      <BackdropLabel left="88%" top="67.5%">0x2F91</BackdropLabel>

      <BackdropNode left="5%" top="80%" opacity={0.09} />
      <BackdropNode left="10%" top="87%" opacity={0.06} />
      <BackdropLine left="5%" top="80%" width="60px" rotate={40} />
      <BackdropLabel left="3.5%" top="89%">EMBED::384D</BackdropLabel>

      {/* One more small cluster near the left column's own system section,
          per the "a few extremely subtle lines/nodes around the left side"
          refinement — kept as faint as everything else here. */}
      <BackdropNode left="1.5%" top="52%" opacity={0.07} />
      <BackdropLine left="1.5%" top="52%" width="34px" rotate={20} opacity={0.04} />

      <BackdropRule left="0" top="42%" width="5px" />
      <BackdropRule left="38%" top="97%" width="110px" />
      <BackdropRule left="60%" top="3%" width="90px" />

      {showConnector && (
        <>
          <BackdropLine className="hidden lg:block" left="31%" top="47%" width="360px" rotate={-6} opacity={0.07} />
          <BackdropLabel className="hidden lg:block" left="46%" top="45%">
            SYSTEM → ACCESS
          </BackdropLabel>
        </>
      )}
    </div>
  )
}

/** Small "you are here" wayfinding line — the one explicit bridge from the
 * landing page's own narrative into this screen, kept to plain text/arrows
 * rather than bordered chips so it stays a quiet detail, not a second banner
 * under the top bar's own "ProjectMind / Account access" status pill. */
function JourneyTrail() {
  return (
    <div className="mb-8 flex flex-wrap items-center gap-x-2 gap-y-1" aria-hidden="true">
      {JOURNEY.map((step, i) => (
        <span key={step} className="flex items-center gap-2">
          {i > 0 && <span style={{ color: 'var(--outline-variant)', fontSize: 11 }}>→</span>}
          <span
            className="t-label-mono"
            style={{ color: step === 'Account Access' ? 'var(--on-surface-variant)' : 'var(--outline)', fontSize: 10.5, letterSpacing: '0.04em' }}
          >
            {step}
          </span>
        </span>
      ))}
    </div>
  )
}

/** Vertical request→plan pipeline — one continuous thin connecting line,
 * small unfilled nodes, monospace labels, and (motion allowing) a small
 * low-opacity indicator that travels the line every several seconds. A
 * system diagram, not an illustration: no fills, no icons, and the pulse
 * never claims to be live status — that's the card's own health-derived
 * "Workspace status" row instead. */
function SystemFlowDiagram() {
  const reduceMotion = useReducedMotion()
  return (
    <div className="mt-10">
      <p className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>
        System pipeline
      </p>
      <div className="relative mt-4 pl-1">
        <span className="absolute w-px" style={{ left: 4, top: '4.5px', bottom: '4.5px', background: 'var(--border-technical)' }} />
        {!reduceMotion && (
          <motion.span
            className="absolute rounded-full"
            style={{ left: '1.5px', height: 6, width: 6, background: 'var(--primary)' }}
            initial={{ top: '0%', opacity: 0 }}
            animate={{ top: ['0%', '100%'], opacity: [0, 0.7, 0.7, 0] }}
            transition={{ duration: 2.8, repeat: Infinity, repeatDelay: 5.5, ease: 'easeInOut' }}
          />
        )}
        {SYSTEM_FLOW.map((step, i) => (
          <div key={step} className="relative z-10 flex items-center gap-3" style={{ paddingBottom: i < SYSTEM_FLOW.length - 1 ? 16 : 0 }}>
            <span
              className="shrink-0 rounded-full"
              style={{ height: 9, width: 9, border: '1px solid var(--outline)', background: 'var(--background)' }}
            />
            <span className="t-label-caps" style={{ color: 'var(--on-surface-variant)', fontSize: 10.5 }}>
              {step}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

/** Compact technical readout — same numbers the landing page's own trust-
 * metrics band shows (see STATS in LandingHero.jsx), laid out as a small
 * bordered data block with a separator per row rather than a bullet list,
 * so it reads as a system spec sheet instead of marketing copy. */
function SystemMetrics() {
  return (
    <div className="mt-10 max-w-sm">
      <p className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>
        ProjectMind system
      </p>
      <div className="glass-panel mt-3" style={{ borderRadius: 8 }}>
        {SYSTEM_METRICS.map((m, i) => (
          <div
            key={m.label}
            className="flex items-center justify-between px-4 py-2.5"
            style={i > 0 ? { borderTop: '1px solid var(--border-technical)' } : undefined}
          >
            <span className="t-label-mono" style={{ color: 'var(--on-surface-variant)', fontSize: 11.5 }}>
              {m.label}
            </span>
            <span className="t-label-caps" style={{ color: 'var(--primary)', fontSize: 10.5 }}>
              {m.value}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

/**
 * Section 7 profile editor — name/email, plus an optional password change
 * gated behind the current one. Renders inline on the signed-in Account
 * card rather than a separate route, since there's nothing else on this
 * screen once signed in to navigate away from. Identity for the PATCH this
 * submits comes from the session token alone (see routes/auth.py); nothing
 * here ever sends a user id.
 */
function ProfileEditor({ user, onDone }) {
  const { updateProfile } = useAuth()
  const [name, setName] = useState(user.name)
  const [email, setEmail] = useState(user.email)
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const submit = async (event) => {
    event.preventDefault()
    setError(null)

    const payload = {}
    if (name.trim() && name.trim() !== user.name) payload.name = name.trim()
    if (email.trim() && email.trim() !== user.email) payload.email = email.trim()
    if (newPassword) {
      payload.current_password = currentPassword
      payload.new_password = newPassword
    }
    if (Object.keys(payload).length === 0) {
      setError('Change something first.')
      return
    }

    setBusy(true)
    try {
      await updateProfile(payload)
      onDone()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <motion.form
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      onSubmit={submit}
      className="mt-4 space-y-3 text-left"
    >
      <label className="block">
        <span className="t-label-caps mb-1.5 block" style={{ color: 'var(--outline)', fontSize: 10 }}>Name</span>
        <input value={name} onChange={(e) => setName(e.target.value)} maxLength={80} className="gm-input w-full px-3 py-2 text-sm" />
      </label>
      <label className="block">
        <span className="t-label-caps mb-1.5 block" style={{ color: 'var(--outline)', fontSize: 10 }}>Email</span>
        <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} className="gm-input w-full px-3 py-2 text-sm" />
      </label>

      <div className="pt-2" style={{ borderTop: '1px solid var(--border-technical)' }}>
        <p className="t-label-caps mt-3" style={{ color: 'var(--outline)', fontSize: 9.5 }}>
          Change password (optional)
        </p>
        <label className="mt-2 block">
          <span className="t-label-caps mb-1.5 block" style={{ color: 'var(--outline)', fontSize: 10 }}>Current password</span>
          <input
            type="password"
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
            className="gm-input w-full px-3 py-2 text-sm"
          />
        </label>
        <label className="mt-2 block">
          <span className="t-label-caps mb-1.5 block" style={{ color: 'var(--outline)', fontSize: 10 }}>New password</span>
          <input
            type="password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            minLength={8}
            className="gm-input w-full px-3 py-2 text-sm"
          />
        </label>
      </div>

      {error && <p className="t-body-md" style={{ color: '#ffb4ab', fontSize: 12.5 }}>{error}</p>}

      <div className="flex gap-2">
        <button type="submit" disabled={busy} className="btn-primary t-label-caps flex-1 py-2.5">
          {busy ? 'Saving…' : 'Save changes'}
        </button>
        <button type="button" onClick={onDone} className="btn-secondary t-label-caps px-4 py-2.5">
          Cancel
        </button>
      </div>
    </motion.form>
  )
}

/**
 * Login / create-account — the one screen between the landing page and the
 * real application, so it borrows the landing page's own tokens directly
 * (.landing-mono is already in scope here via Layout.jsx's bare-chrome
 * wrapper) rather than a second design system: same grid-bg/scanline
 * backdrop the app shell uses, same glass-panel card, same t-headline/
 * t-label-caps type scale, same gm-input/btn-primary form primitives.
 */
export default function Account() {
  const { user, signup, login, logout } = useAuth()
  const navigate = useNavigate()
  const [mode, setMode] = useState('login')
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [editingProfile, setEditingProfile] = useState(false)
  // Real backend health (same call/shape TopBar.jsx already uses) — the
  // card's "Workspace status" row reflects this, not a hardcoded dot.
  const [health, setHealth] = useState(null)

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null))
  }, [])

  const submit = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      if (mode === 'signup') await signup(email, password, name)
      else await login(email, password)
      navigate('/dashboard')
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const statusColor = health?.status === 'ok' ? '#7bcf9f' : health ? '#e3ab6a' : 'var(--outline)'
  const statusLabel = health?.status === 'ok' ? 'System ready' : health ? 'System degraded' : 'Checking system…'

  if (user) {
    return (
      <div className="relative flex min-h-[calc(100vh-4rem)] flex-col items-center justify-center overflow-hidden px-6 py-14" style={{ background: 'var(--background)' }}>
        <div className="grid-bg pointer-events-none absolute inset-0 z-0" />
        <AccountBackdrop />
        <div className="scanline" />
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="relative z-10 w-full max-w-sm text-center"
        >
          <span
            className="t-label-caps inline-block px-3 py-1"
            style={{ border: '1px solid var(--border-technical)', background: 'var(--surface-glass)', color: 'var(--on-surface-variant)', borderRadius: 999 }}
          >
            Account
          </span>
          <h1 className="t-headline-xl mt-5" style={{ color: 'var(--primary)' }}>
            Signed in
          </h1>
          <p className="t-body-md mt-3" style={{ color: 'var(--on-surface-variant)' }}>
            Needed for AI chat, team workspaces and notifications.
          </p>

          <div className="glass-panel mt-8 p-7 text-left" style={{ borderRadius: 14, border: '1px solid var(--outline-variant)' }}>
            <div
              className="mx-auto grid h-12 w-12 place-items-center rounded-full"
              style={{ background: 'var(--surface-container-highest)', border: '1px solid var(--border-technical)' }}
            >
              <span className="material-symbols-outlined" style={{ fontSize: 22, color: 'var(--on-surface-variant)' }}>
                person
              </span>
            </div>
            <p className="t-label-mono mt-4 text-center" style={{ color: 'var(--on-surface)', fontSize: 16 }}>
              {user.name}
            </p>
            <p className="t-body-md text-center" style={{ color: 'var(--on-surface-variant)', fontSize: 13 }}>
              {user.email}
            </p>

            {editingProfile ? (
              <ProfileEditor user={user} onDone={() => setEditingProfile(false)} />
            ) : (
              <button
                type="button"
                onClick={() => setEditingProfile(true)}
                className="t-label-mono mt-4 block w-full text-center transition hover:opacity-75"
                style={{ color: 'var(--outline)', fontSize: 12 }}
              >
                Edit profile
              </button>
            )}

            <button onClick={logout} className="btn-secondary t-label-caps mt-6 w-full px-4 py-2.5">
              Sign out
            </button>

            <div className="mt-6" style={{ borderTop: '1px solid var(--border-technical)' }} />
            <div className="mt-4 flex items-center justify-between">
              <span className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 9.5 }}>
                Workspace status
              </span>
              <span className="t-label-mono flex items-center gap-1.5" style={{ color: 'var(--on-surface-variant)', fontSize: 11 }}>
                <span className="h-1.5 w-1.5 rounded-full" style={{ background: statusColor }} />
                {statusLabel}
              </span>
            </div>
          </div>
        </motion.div>
      </div>
    )
  }

  return (
    <div className="relative min-h-[calc(100vh-4rem)] overflow-hidden" style={{ background: 'var(--background)' }}>
      <div className="grid-bg pointer-events-none absolute inset-0 z-0" />
      <AccountBackdrop showConnector />
      <div className="scanline" />

      <div className="container-wide relative z-10 grid items-start gap-12 py-14 lg:grid-cols-[1.15fr_0.85fr] lg:gap-14">
        {/* Left: a technical system, not empty space — same "real capability,
            not marketing" tone the landing page uses, structured identity →
            headline → description → capabilities → pipeline → metrics. */}
        <motion.div
          initial={{ opacity: 0, x: -16 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.5 }}
          className="order-2 lg:order-1"
        >
          <JourneyTrail />

          <h1 className="t-headline-xl" style={{ color: 'var(--primary)' }}>
            Build with
            <br />
            <span style={{ color: 'var(--on-surface-variant)' }}>better context.</span>
          </h1>
          <p className="t-body-lg mt-5 max-w-md" style={{ color: 'var(--on-surface-variant)' }}>
            Your projects, conversations, evaluations and planning workspace — in one place.
          </p>

          <div className="mt-8 grid grid-cols-1 gap-3 sm:grid-cols-2">
            {CAPABILITIES.map((c) => (
              <span key={c.label} className="trust-check">
                <span className="material-symbols-outlined" aria-hidden="true">
                  {c.icon}
                </span>
                <span className="t-label-caps" style={{ fontSize: 10.5 }}>
                  {c.label}
                </span>
              </span>
            ))}
          </div>

          <SystemFlowDiagram />
          <SystemMetrics />
        </motion.div>

        {/* Right: the actual form, as a system panel rather than a bare page */}
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.1 }}
          className="order-1 flex justify-center lg:order-2 lg:justify-end lg:pt-6"
        >
          <div className="auth-panel glass-panel w-full max-w-md p-8" style={{ borderRadius: 14, border: '1px solid var(--outline-variant)' }}>
            <div className="flex items-center justify-between">
              <span
                className="t-label-caps inline-flex items-center gap-1.5 px-3 py-1"
                style={{ border: '1px solid var(--outline-variant)', background: 'var(--surface-glass)', color: 'var(--on-surface)', borderRadius: 999 }}
              >
                <span className="h-1.5 w-1.5 rounded-full" style={{ background: 'var(--primary)' }} />
                Account access
              </span>
              <span className="t-label-mono" style={{ color: 'var(--outline)', fontSize: 10.5 }}>
                {mode === 'login' ? '01 / SIGN-IN' : '01 / CREATE'}
              </span>
            </div>
            <div className="mt-5" style={{ borderTop: '1px solid var(--border-technical)' }} />

            <h2 className="t-headline-md mt-6" style={{ color: 'var(--primary)' }}>
              {mode === 'login' ? 'Sign in' : 'Create account'}
            </h2>
            <p className="t-body-md mt-2" style={{ color: 'var(--on-surface-variant)', fontSize: 13 }}>
              Needed for AI chat, team workspaces and notifications — résumé matching, idea checks, favourites and history all work without one.
            </p>

            <motion.form key={mode} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.25 }} onSubmit={submit} className="mt-7 space-y-4">
              {mode === 'signup' && (
                <label className="block">
                  <span className="t-label-caps mb-1.5 block" style={{ color: 'var(--outline)', fontSize: 10 }}>Name</span>
                  <input value={name} onChange={(e) => setName(e.target.value)} required autoFocus maxLength={80} className="gm-input w-full px-4 py-3.5 text-sm" />
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
                  className="gm-input w-full px-4 py-3.5 text-sm"
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
                  className="gm-input w-full px-4 py-3.5 text-sm"
                />
              </label>

              {error && <p className="t-body-md" style={{ color: '#ffb4ab', fontSize: 13 }}>{error}</p>}

              <button type="submit" disabled={busy} className="btn-primary t-label-caps w-full py-3.5">
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
            </motion.form>

            <div className="mt-7" style={{ borderTop: '1px solid var(--border-technical)' }} />
            <div className="mt-4 flex items-center justify-between">
              <span className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 9.5 }}>
                Workspace status
              </span>
              <span className="t-label-mono flex items-center gap-1.5" style={{ color: 'var(--on-surface-variant)', fontSize: 11 }}>
                <span className="h-1.5 w-1.5 rounded-full" style={{ background: statusColor }} />
                {statusLabel}
              </span>
            </div>
          </div>
        </motion.div>
      </div>
    </div>
  )
}
