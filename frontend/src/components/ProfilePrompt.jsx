import { useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import api from '../services/api'
import useProfile, { announceProfileChanged } from '../hooks/useProfile'

/**
 * A dismissible nudge for signed-in accounts whose profile is not complete.
 *
 * Deliberately never blocking: it sits above the page, links into the setup
 * flow, and "Not now" is remembered server-side so it does not return on every
 * visit or device. An account that is already complete, or that dismissed it,
 * sees nothing. Existing accounts (no profile yet) get the same single prompt
 * as new ones rather than being forced through onboarding.
 */
export default function ProfilePrompt() {
  const { profile, status } = useProfile()
  const { pathname } = useLocation()
  const [hidden, setHidden] = useState(false)

  if (status !== 'ready' || !profile || hidden) return null
  if (pathname.startsWith('/profile') || pathname.startsWith('/account')) return null
  if (profile.completion.status === 'complete' || profile.onboarding_dismissed) return null

  const started = profile.completion.status === 'in_progress'

  const dismiss = async () => {
    setHidden(true)
    try {
      await api.saveLearnerProfile({ onboarding_dismissed: true })
      announceProfileChanged()
    } catch {
      /* The prompt is already hidden for this visit; it may reappear next time. */
    }
  }

  return (
    <div
      role="region"
      aria-label="Complete your profile"
      className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6"
      style={{ borderBottom: '1px solid var(--border-technical)', background: 'var(--surface-container-low)' }}
    >
      <p className="t-body-md" style={{ color: 'var(--on-surface)', fontSize: 13 }}>
        {started ? `Your profile is ${profile.completion.percent}% complete.` : 'Tell us your skills and goals to get suggestions that fit you.'}
        <span style={{ color: 'var(--on-surface-variant)' }}> It takes a couple of minutes and is optional.</span>
      </p>
      <div className="flex items-center gap-2">
        <Link to="/profile?setup=1" className="t-label-caps px-3.5 py-1.5 transition hover:opacity-85" style={{ background: 'var(--primary)', color: 'var(--on-primary)', borderRadius: 8 }}>
          {started ? 'Continue' : 'Set up profile'}
        </Link>
        <button type="button" onClick={dismiss} className="t-label-caps px-3 py-1.5" style={{ color: 'var(--on-surface-variant)' }}>
          Not now
        </button>
      </div>
    </div>
  )
}
