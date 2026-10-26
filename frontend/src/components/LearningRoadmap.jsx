import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import useAuth from '../hooks/useAuth.jsx'
import api from '../services/api'
import Panel from './Panel'
import { Spinner, ErrorNotice } from './Feedback'

const muted = { color: 'var(--on-surface-variant)' }

const STATUSES = [
  { value: 'not_started', label: 'Not started' },
  { value: 'in_progress', label: 'In progress' },
  { value: 'completed', label: 'Completed' },
]

const KIND_LABEL = {
  learn: 'Learn',
  improve: 'Practise',
  confirm: 'Check',
  prerequisite: 'Foundation',
  concepts: 'Pick up while building',
}

function StatusControl({ step, busy, onChange }) {
  return (
    <div role="group" aria-label={`Status of step ${step.number}: ${step.skill}`} className="mt-3 flex flex-wrap gap-1.5">
      {STATUSES.map((s) => {
        const on = step.status === s.value
        return (
          <button
            key={s.value}
            type="button"
            aria-pressed={on}
            disabled={busy}
            onClick={() => !on && onChange(step.id, s.value)}
            className="t-label-mono px-2.5 py-1 transition hover:opacity-85 disabled:opacity-50"
            style={{
              fontSize: 11,
              borderRadius: 999,
              border: `1px solid ${on ? 'var(--primary)' : 'var(--border-technical)'}`,
              background: on ? 'var(--primary)' : 'transparent',
              color: on ? 'var(--on-primary)' : 'var(--on-surface-variant)',
            }}
          >
            {s.label}
          </button>
        )
      })}
    </div>
  )
}

function Step({ step, busy, onStatus }) {
  const done = step.status === 'completed'
  return (
    <li className="p-4" style={{ border: '1px solid var(--border-technical)', borderRadius: 8, opacity: done ? 0.75 : 1 }}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="t-label-mono" style={{ color: 'var(--on-surface)', fontSize: 13.5 }}>
          <span style={{ color: 'var(--primary)' }}>{step.number}.</span> {step.skill}
        </h3>
        <span className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>
          {KIND_LABEL[step.kind]}
          {!step.from_project_requirements && ' · not listed by the project'}
        </span>
      </div>
      {step.kind === 'concepts' && (
        <p className="t-body-md mt-1" style={{ ...muted, fontSize: 12.5 }}>{step.skills.join(' · ')}</p>
      )}
      <p className="t-body-md mt-2" style={{ ...muted, fontSize: 12.5 }}>
        <strong style={{ color: 'var(--on-surface)' }}>Why: </strong>
        {step.why_it_matters}
      </p>
      <p className="t-body-md mt-1" style={{ ...muted, fontSize: 12.5 }}>
        <strong style={{ color: 'var(--on-surface)' }}>For you: </strong>
        {step.why_for_you}
        {step.evidence.source !== 'none' && step.evidence.self_reported === false && ' (inferred, not confirmed)'}
      </p>
      {step.matches_your_goal && (
        <p className="t-body-md mt-1" style={{ ...muted, fontSize: 12.5 }}>Matches your goal: “{step.matches_your_goal}”</p>
      )}
      {step.prerequisites.length > 0 && (
        <p className="t-body-md mt-1" style={{ ...muted, fontSize: 12.5 }}>
          <strong style={{ color: 'var(--on-surface)' }}>Before this: </strong>
          {step.prerequisites.map((p) => (p.status === 'on_profile' ? `${p.skill} (on your profile)` : `${p.skill} (earlier step)`)).join(', ')}
        </p>
      )}
      <p className="t-body-md mt-2" style={{ color: 'var(--on-surface)', fontSize: 12.5 }}>
        <span className="t-label-caps" style={{ color: 'var(--primary)', fontSize: 10 }}>Practice </span>
        {step.practice_task}
      </p>
      <p className="t-body-md mt-1" style={{ ...muted, fontSize: 12.5 }}>
        <span className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>Done when </span>
        {step.completion_criterion}
      </p>
      {step.resources.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {step.resources.map((r) => (
            <a
              key={r.url}
              href={r.url}
              target="_blank"
              rel="noreferrer"
              title={r.title}
              className="t-label-mono px-2 py-1 transition hover:opacity-75"
              style={{ background: 'var(--surface-container-low)', color: 'var(--on-surface-variant)', fontSize: 11, borderRadius: 6 }}
            >
              {r.platform}
            </a>
          ))}
        </div>
      )}
      <StatusControl step={step} busy={busy} onChange={onStatus} />
      {done && step.kind !== 'concepts' && (
        <p className="t-body-md mt-2" style={{ ...muted, fontSize: 12 }}>
          Completing a step does not change your profile.{' '}
          <Link to="/profile" className="underline" style={{ color: 'var(--primary)' }}>Add or update {step.skill} yourself</Link> if you want it recorded.
        </p>
      )}
      {step.after && (
        <p className="t-body-md mt-2" style={{ color: 'var(--outline)', fontSize: 11.5 }}>Next: {step.after.skill}</p>
      )}
    </li>
  )
}

function Roadmap({ roadmap, onStatus, onReset, busy, actionError }) {
  const { profile, steps, overview, notes, progress, retired_steps: retired, ordering } = roadmap
  const [confirming, setConfirming] = useState(false)
  const hasProgress = progress.in_progress + progress.completed > 0 || retired.length > 0

  return (
    <div>
      {profile.status !== 'complete' && (
        <p className="t-body-md p-3" role="note" style={{ background: 'var(--surface-container-low)', borderRadius: 8, ...muted, fontSize: 12.5 }}>
          {profile.has_skills ? `Your profile is ${profile.percent}% complete, so this roadmap may include things you already know. ` : 'Your profile lists no skills yet, so the roadmap starts from the basics. '}
          <Link to="/profile?setup=1" className="underline" style={{ color: 'var(--primary)' }}>
            {profile.status === 'not_started' ? 'Add your profile' : 'Update your profile'}
          </Link>
        </p>
      )}

      {notes.filter((n) => !n.startsWith('Your profile lists no skills')).map((n) => (
        <p key={n} className="t-body-md mt-2" style={{ ...muted, fontSize: 12.5 }}>{n}</p>
      ))}

      {steps.length === 0 ? (
        <p className="t-body-md mt-3" style={{ ...muted, fontSize: 13 }}>
          {roadmap.requirements.total === 0 ? 'There are no listed requirements to build a roadmap from.' : overview.finish}
        </p>
      ) : (
        <>
          <p className="t-label-mono mt-3" style={{ color: 'var(--on-surface)', fontSize: 12.5 }} aria-label="Progress">
            {progress.completed} of {progress.total} steps completed
            {progress.in_progress > 0 && ` · ${progress.in_progress} in progress`}
          </p>
          {overview.already_covered.length > 0 && (
            <p className="t-body-md mt-1" style={{ ...muted, fontSize: 12 }}>
              Skipped because your profile already covers them: {overview.already_covered.join(', ')}.
            </p>
          )}
          <ol className="mt-3 space-y-3" aria-label="Learning steps">
            {steps.map((s) => (
              <Step key={s.id} step={s} busy={busy} onStatus={onStatus} />
            ))}
          </ol>
          <p className="t-body-md mt-3" style={{ color: 'var(--on-surface)', fontSize: 12.5 }}>{overview.finish}</p>
        </>
      )}

      {retired.length > 0 && (
        <p className="t-body-md mt-3" style={{ ...muted, fontSize: 12 }}>
          Earlier steps no longer needed for your current profile: {retired.map((r) => `${r.label} (${r.status.replace('_', ' ')})`).join(', ')}.
        </p>
      )}
      {actionError && <p role="alert" className="t-body-md mt-3" style={{ color: '#ffb4ab', fontSize: 12.5 }}>{actionError}</p>}

      {hasProgress && (
        <div className="mt-4">
          {confirming ? (
            <div className="flex flex-wrap items-center gap-3" role="alertdialog" aria-label="Confirm reset">
              <span className="t-body-md" style={{ ...muted, fontSize: 12.5 }}>Clear all recorded progress for this project? This cannot be undone.</span>
              <button type="button" disabled={busy} onClick={() => { setConfirming(false); onReset() }} className="t-label-caps px-3 py-1.5" style={{ background: '#ffb4ab', color: '#1a0000', borderRadius: 8, fontSize: 10.5 }}>
                Yes, reset progress
              </button>
              <button type="button" onClick={() => setConfirming(false)} className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10.5 }}>Cancel</button>
            </div>
          ) : (
            <button type="button" onClick={() => setConfirming(true)} className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10.5 }}>
              Reset progress…
            </button>
          )}
        </div>
      )}

      <details className="mt-4">
        <summary className="t-label-caps cursor-pointer" style={{ color: 'var(--outline)', fontSize: 10 }}>How the order is decided</summary>
        <p className="t-body-md mt-2" style={{ ...muted, fontSize: 12 }}>{ordering.note}</p>
        {ordering.cycle_detected && <p className="t-body-md mt-1" style={{ ...muted, fontSize: 12 }}>Some prerequisite information was inconsistent, so part of the order falls back to the standard sequence.</p>}
      </details>
      <p className="t-body-md mt-3" style={{ color: 'var(--outline)', fontSize: 11.5 }}>{roadmap.disclaimer}</p>
    </div>
  )
}

/**
 * "Your learning roadmap" for this project: ordered steps built from the
 * signed-in account's saved profile (GET /api/roadmap/me), with the user's own
 * recorded progress. Progress is only ever set by the user here; completing a
 * step never edits the profile.
 */
export default function LearningRoadmap({ projectId }) {
  const { user, loading: authLoading } = useAuth()
  const [status, setStatus] = useState('idle') // idle | loading | done | error
  const [roadmap, setRoadmap] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState(null)

  const load = useCallback(async () => {
    setStatus('loading')
    setError(null)
    try {
      const { data } = await api.personalRoadmap(projectId)
      setRoadmap(data)
      setStatus('done')
    } catch (err) {
      setError(err.message)
      setStatus('error')
    }
  }, [projectId])

  useEffect(() => {
    if (authLoading || !user) return
    load()
  }, [authLoading, user, load])

  const run = async (call, pick = (res) => res.data) => {
    setBusy(true)
    setActionError(null)
    try {
      setRoadmap(pick(await call()))
    } catch (err) {
      setActionError(err.message)
    } finally {
      setBusy(false)
    }
  }

  if (authLoading) return null

  if (!user) {
    return (
      <Panel icon="route" title="Your learning roadmap" description="A step-by-step plan from your own skills to this project." compact>
        <p className="t-body-md" style={{ ...muted, fontSize: 13 }}>
          <Link to="/account" className="underline" style={{ color: 'var(--primary)' }}>Sign in</Link> and add your skills to get an ordered plan you can track.
        </p>
      </Panel>
    )
  }

  return (
    <Panel icon="route" title="Your learning roadmap" description="Ordered from your saved profile and this project’s listed requirements." compact>
      {status === 'loading' && <Spinner label="Building your roadmap…" />}
      {status === 'error' && <ErrorNotice message={error} onRetry={load} />}
      {status === 'done' && roadmap && (
        <Roadmap
          roadmap={roadmap}
          busy={busy}
          actionError={actionError}
          onStatus={(stepId, value) => run(() => api.setRoadmapStep(projectId, stepId, value))}
          onReset={() => run(() => api.resetRoadmap(projectId), (res) => res.data.roadmap)}
        />
      )}
    </Panel>
  )
}
