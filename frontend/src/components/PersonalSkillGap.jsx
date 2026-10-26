import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import useAuth from '../hooks/useAuth.jsx'
import api from '../services/api'
import Panel from './Panel'
import { Spinner, ErrorNotice } from './Feedback'

const muted = { color: 'var(--on-surface-variant)' }

const PRIORITY_STYLE = {
  high: { color: '#ffb4ab', label: 'High priority' },
  medium: { color: '#e3ab6a', label: 'Medium priority' },
  low: { color: 'var(--outline)', label: 'Lower priority' },
}

const EVIDENCE_TEXT = {
  profile: (e) => `On your profile${e.level ? ` at ${e.level} (self-reported)` : ''}`,
  past_project: () => 'Used in a past project — level not stated',
  related: (e) => `Only a related skill is listed: ${e.skill} (inferred, not confirmed)`,
  none: () => 'Not on your profile',
}

function GapCard({ item }) {
  const priority = item.priority ? PRIORITY_STYLE[item.priority.level] : null
  return (
    <li className="p-3" style={{ border: '1px solid var(--border-technical)', borderRadius: 8 }}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="t-label-mono" style={{ color: 'var(--on-surface)' }}>
          {item.skill}
          <span className="ml-2" style={{ color: 'var(--outline)', fontSize: 11 }}>
            {item.kind === 'technology' ? 'project technology' : 'required skill'}
          </span>
        </p>
        {priority && (
          <span className="t-label-caps" style={{ color: priority.color, fontSize: 10 }}>
            {priority.label}
          </span>
        )}
      </div>
      <p className="t-body-md mt-1" style={{ ...muted, fontSize: 12.5 }}>
        {item.classification === 'needs_improvement' ? 'Needs improvement · ' : item.classification === 'unclear' ? 'Unclear · ' : 'Not on your profile · '}
        {EVIDENCE_TEXT[item.evidence.source](item.evidence)}
      </p>
      <p className="t-body-md mt-1" style={{ ...muted, fontSize: 12.5 }}>{item.why_it_matters}</p>
      {item.priority && (
        <ul className="mt-1 list-disc pl-5" style={{ ...muted, fontSize: 12 }}>
          {item.priority.reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}
      {item.prerequisites.length > 0 && (
        <p className="t-body-md mt-1" style={{ ...muted, fontSize: 12 }}>
          Best learned after: {item.prerequisites.join(', ')} (the language the rest of the stack is written in).
        </p>
      )}
      {item.next_step && (
        <p className="t-body-md mt-2" style={{ color: 'var(--on-surface)', fontSize: 12.5 }}>
          <span className="t-label-caps" style={{ color: 'var(--primary)', fontSize: 10 }}>Next step </span>
          {item.next_step}
        </p>
      )}
      {item.resources.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {item.resources.map((r) => (
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
    </li>
  )
}

function Group({ title, hint, items, children }) {
  if (!items.length) return null
  return (
    <section className="mt-5" aria-label={title}>
      <h3 className="t-label-caps" style={{ color: 'var(--on-surface)', fontSize: 11 }}>
        {title} · {items.length}
      </h3>
      {hint && <p className="t-body-md mt-1" style={{ ...muted, fontSize: 12 }}>{hint}</p>}
      <ul className="mt-2 space-y-2">{children}</ul>
    </section>
  )
}

/**
 * "Your skill gap for this project" — the signed-in account's saved profile
 * against this catalogue project (GET /api/skill-gap/me). Sits above the
 * anonymous "Am I ready for this?" check, which stays as it was for visitors
 * who just want to type a few skills.
 */
export default function PersonalSkillGap({ projectId }) {
  const { user, loading: authLoading } = useAuth()
  const [status, setStatus] = useState('idle') // idle | loading | done | error
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    setStatus('loading')
    setError(null)
    try {
      const { data } = await api.personalSkillGap(projectId)
      setResult(data)
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

  if (authLoading) return null

  if (!user) {
    return (
      <Panel icon="person_search" title="Your skill gap for this project" description="Compare your own saved skills with what this project needs." compact>
        <p className="t-body-md" style={{ ...muted, fontSize: 13 }}>
          <Link to="/account" className="underline" style={{ color: 'var(--primary)' }}>Sign in</Link> and add your skills to see which ones this project needs that you already have, and what to practise first.
        </p>
      </Panel>
    )
  }

  return (
    <Panel icon="person_search" title="Your skill gap for this project" description="Your saved profile against this project’s listed requirements." compact>
      {status === 'loading' && <Spinner label="Comparing your profile…" />}
      {status === 'error' && <ErrorNotice message={error} onRetry={load} />}
      {status === 'done' && result && <Result result={result} />}
    </Panel>
  )
}

function Result({ result }) {
  const { profile, summary, items, notes, requirements, ranking, rules } = result
  const gaps = items.filter((i) => i.classification === 'missing' || i.classification === 'needs_improvement')
  const unclear = items.filter((i) => i.classification === 'unclear')
  const have = items.filter((i) => i.classification === 'have')

  return (
    <div>
      {profile.status !== 'complete' && (
        <p className="t-body-md p-3" role="note" style={{ background: 'var(--surface-container-low)', borderRadius: 8, ...muted, fontSize: 12.5 }}>
          {profile.has_skills
            ? `Your profile is ${profile.percent}% complete, so this may miss skills you have. `
            : 'You have not added any skills yet, so everything below shows as not on your profile. '}
          <Link to="/profile?setup=1" className="underline" style={{ color: 'var(--primary)' }}>
            {profile.status === 'not_started' ? 'Add your profile' : 'Update your profile'}
          </Link>
        </p>
      )}

      {requirements.total === 0 ? (
        <p className="t-body-md mt-3" style={{ ...muted, fontSize: 13 }}>
          {notes[0] ?? 'This project lists no skills or technologies, so there is nothing to compare.'}
        </p>
      ) : (
        <>
          <p className="t-label-mono mt-3" style={{ color: 'var(--on-surface)', fontSize: 12.5 }} aria-label="Summary">
            {summary.have} covered · {summary.needs_improvement} to improve · {summary.unclear} unclear · {summary.missing} not on your profile
          </p>
          {notes.filter((n) => !n.startsWith('Your profile lists no skills')).map((n) => (
            <p key={n} className="t-body-md mt-1" style={{ ...muted, fontSize: 12 }}>{n}</p>
          ))}
          {ranking.note && <p className="t-body-md mt-1" style={{ ...muted, fontSize: 12 }}>{ranking.note}</p>}

          <Group title="Worth working on" hint="Missing or below the level this project’s difficulty suggests." items={gaps}>
            {gaps.map((i) => <GapCard key={i.skill} item={i} />)}
          </Group>
          <Group title="Unclear" hint="There is some evidence, but not enough to say. Update your profile to settle these." items={unclear}>
            {unclear.map((i) => <GapCard key={i.skill} item={i} />)}
          </Group>
          <Group title="Already covered" items={have}>
            {have.map((i) => (
              <li key={i.skill} className="t-body-md" style={{ ...muted, fontSize: 12.5 }}>
                <span style={{ color: '#7bcf9f' }}>✓</span> {i.skill} — {EVIDENCE_TEXT[i.evidence.source](i.evidence)}
              </li>
            ))}
          </Group>
        </>
      )}

      <details className="mt-5">
        <summary className="t-label-caps cursor-pointer" style={{ color: 'var(--outline)', fontSize: 10 }}>How this is decided</summary>
        <p className="t-body-md mt-2" style={{ ...muted, fontSize: 12 }}>{rules.bar}</p>
        <ul className="mt-2 list-disc pl-5" style={{ ...muted, fontSize: 12 }}>
          {Object.entries(rules.priority).map(([k, v]) => (
            <li key={k}><strong>{k}</strong>: {v}</li>
          ))}
        </ul>
      </details>
      <p className="t-body-md mt-3" style={{ color: 'var(--outline)', fontSize: 11.5 }}>{result.disclaimer}</p>
    </div>
  )
}
