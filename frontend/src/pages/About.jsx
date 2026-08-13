import { useState } from 'react'
import { motion } from 'framer-motion'
import api from '../services/api'
import PageHeader from '../components/PageHeader'
import FeedbackForm from '../components/FeedbackForm'
import Panel from '../components/Panel'

function UniquenessChecker() {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const check = async () => {
    if (!title.trim() && !description.trim()) return
    setBusy(true)
    setError(null)
    try {
      const { data } = await api.uniqueness(title, description)
      setResult(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Panel
      icon="fingerprint"
      title="Is my project idea original?"
      description="Describe an idea and we will check it against the catalogue by meaning, so a reworded version of an existing project is still detected."
    >
      <div className="space-y-3">
        <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Project title" className="gm-input w-full px-3 py-2 text-sm" />
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Describe what it does…"
          rows={3}
          className="gm-input w-full px-3 py-2 text-sm"
        />
        <button
          onClick={check}
          disabled={busy}
          className="btn-primary t-label-caps px-4 py-2"
        >
          {busy ? 'Checking…' : 'Check originality'}
        </button>
      </div>

      {error && <p className="t-body-md mt-3" style={{ color: '#ffb4ab', fontSize: 13 }}>{error}</p>}

      {result && (
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="mt-4">
          <div
            className="p-4"
            style={{
              border: `1px solid ${result.is_unique ? 'var(--border-technical)' : 'var(--primary)'}`,
              background: 'var(--surface-container-low)',
              borderRadius: 8,
            }}
          >
            <p className="t-label-mono" style={{ color: 'var(--primary)' }}>
              {result.is_unique ? 'Looks original' : 'Similar projects already exist'}
            </p>
            <p className="t-body-md mt-1" style={{ color: 'var(--on-surface-variant)' }}>
              Closest match scored {(result.highest_similarity * 100).toFixed(0)}% similarity
              (flagged above {(result.threshold * 100).toFixed(0)}%).
            </p>

            {result.closest_matches?.length > 0 && (
              <ul className="t-body-md mt-3 space-y-1" style={{ color: 'var(--on-surface-variant)' }}>
                {result.closest_matches.map((m) => (
                  <li key={m.project_id}>
                    {(m.similarity * 100).toFixed(0)}% — {m.title}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </motion.div>
      )}
    </Panel>
  )
}

export default function About() {
  return (
    <div className="mx-auto max-w-6xl space-y-6 px-6 py-14">
      <PageHeader
        title="About ProjectMind AI"
        description="How the ranking works, and what the app stores about you."
      />

      <Panel icon="insights" title="How the recommendations work">
        <div className="t-body-md space-y-3" style={{ color: 'var(--on-surface-variant)' }}>
          <p>
            Search combines two retrieval methods. <strong style={{ color: 'var(--on-surface)' }}>
            Sentence embeddings</strong> capture what a query means, so "a system that
            spots diseases from photos of crops" finds the right project without sharing
            a single keyword with its title. <strong style={{ color: 'var(--on-surface)' }}>
            BM25</strong> handles exact technical terms, where embeddings are weak.
          </p>
          <p>
            Neither alone is enough. Measured over 25 labelled test queries across the
            full 500-project catalogue, embeddings alone scored 0.866 nDCG@5 and BM25
            alone 0.737 — the two combined reach
            <strong style={{ color: 'var(--on-surface)' }}> 0.892</strong>, with
            every query returning a relevant result first.
          </p>
          <p>
            Filters are applied <em>before</em> ranking rather than after. Ranking first
            and filtering the top results afterwards is the common approach, and it
            frequently returns nothing at all.
          </p>
        </div>
      </Panel>

      <UniquenessChecker />

      <FeedbackForm
        title="Send feedback"
        hint="Tell us how the recommendations are working. Ratings and comments are stored against your account or device id only."
      />

      <Panel icon="shield_lock" title="Privacy">
        <p className="t-body-md" style={{ color: 'var(--on-surface-variant)' }}>
          An account is optional — it's only needed for team workspaces and notifications.
          Without one, favourites and history are tied to a random identifier stored in
          this browser, so clearing site data resets them. Nothing you search is linked
          to a personal identity beyond what an account you create yourself holds.
        </p>
      </Panel>
    </div>
  )
}
