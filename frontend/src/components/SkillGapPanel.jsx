import { useState } from 'react'
import { motion } from 'framer-motion'
import api from '../services/api'
import Panel from './Panel'

function LearningPath({ skills }) {
  const [path, setPath] = useState(null)
  const [status, setStatus] = useState('idle')

  const load = async () => {
    setStatus('loading')
    try {
      const { data } = await api.learningPath(skills)
      setPath(data)
      setStatus('done')
    } catch {
      setStatus('error')
    }
  }

  if (status === 'idle') {
    return (
      <button onClick={load} className="btn-secondary t-label-caps mt-4 px-3 py-1.5">
        Show me where to learn these
      </button>
    )
  }

  if (status === 'loading') return <p className="t-label-mono mt-4" style={{ color: 'var(--outline)', fontSize: 12 }}>Finding resources…</p>
  if (status === 'error') return <p className="t-body-md mt-4" style={{ color: '#ffb4ab', fontSize: 12 }}>Could not load resources — try again.</p>

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="mt-4 space-y-3 pt-4" style={{ borderTop: '1px solid var(--border-technical)' }}>
      {path.map(({ skill, resources }) => (
        <div key={skill}>
          <p className="t-label-mono" style={{ color: 'var(--on-surface)', fontSize: 12.5 }}>{skill}</p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {resources.map((r) => (
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
        </div>
      ))}
    </motion.div>
  )
}

/**
 * "Am I ready for this?" skill-gap check, on demand.
 *
 * `onCheck(skills) => Promise<{data}>` is the only thing that differs
 * between a catalogue project (pages/ProjectDetail.jsx, POST /api/skill-gap
 * keyed by project_id) and a generated idea (pages/IdeaDetail.jsx, POST
 * /api/idea/skill-gap — a generated idea has no project_id, see
 * backend/routes/ideas.py) — both share this exact component rather than
 * forking it.
 */
export default function SkillGapPanel({ onCheck }) {
  const [input, setInput] = useState('')
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const analyse = async () => {
    const skills = input.split(',').map((s) => s.trim()).filter(Boolean)
    if (!skills.length) return
    setBusy(true)
    setError(null)
    try {
      const { data } = await onCheck(skills)
      setResult(data)
    } catch (err) {
      setResult(null)
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Panel icon="fact_check" title="Am I ready for this?" description="List skills you already have, separated by commas.">
      <div className="flex gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && analyse()}
          placeholder="Python, REST APIs, pandas"
          className="gm-input flex-1 px-3 py-2 text-sm"
        />
        <button onClick={analyse} disabled={busy} className="btn-primary t-label-caps shrink-0 px-4 py-2">
          {busy ? '…' : 'Check'}
        </button>
      </div>

      {error && <p className="t-body-md mt-3" style={{ color: '#ffb4ab', fontSize: 13 }}>{error}</p>}

      {result && (
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="mt-4">
          <div className="flex items-center gap-3">
            <div className="h-2 flex-1 overflow-hidden rounded-full" style={{ background: 'var(--surface-container-high)' }}>
              <motion.div
                className="h-full rounded-full"
                style={{ background: 'var(--primary)' }}
                initial={{ width: 0 }}
                animate={{ width: `${result.readiness_percent}%` }}
                transition={{ duration: 0.6 }}
              />
            </div>
            <span className="t-label-mono tabular-nums" style={{ color: 'var(--on-surface)' }}>{result.readiness_percent}% ready</span>
          </div>

          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <div>
              <p className="t-label-caps" style={{ color: 'var(--on-surface-variant)', fontSize: 10 }}>You have</p>
              <ul className="t-body-md mt-1 space-y-1" style={{ color: 'var(--on-surface-variant)' }}>
                {result.skills_you_have.length
                  ? result.skills_you_have.map((s) => <li key={s}>✓ {s}</li>)
                  : <li style={{ color: 'var(--outline)' }}>None yet</li>}
              </ul>
            </div>
            <div>
              <p className="t-label-caps" style={{ color: 'var(--on-surface-variant)', fontSize: 10 }}>To learn</p>
              <ul className="t-body-md mt-1 space-y-1" style={{ color: 'var(--on-surface-variant)' }}>
                {result.skills_to_learn.map((s) => <li key={s}>○ {s}</li>)}
              </ul>
            </div>
          </div>

          {result.skills_to_learn.length > 0 && <LearningPath skills={result.skills_to_learn} />}
        </motion.div>
      )}
    </Panel>
  )
}
