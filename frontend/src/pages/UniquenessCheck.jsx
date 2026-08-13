import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import api from '../services/api'
import useFavorites from '../hooks/useFavorites'
import ProjectCard from '../components/ProjectCard'
import PageHeader from '../components/PageHeader'
import Panel from '../components/Panel'
import GettingStartedPanel from '../components/GettingStartedPanel'
import { Spinner, ErrorNotice, EmptyState } from '../components/Feedback'

/** Similarity bar + View/Select/Compare actions below the reused, unchanged
 * ProjectCard — same composition ResumeMatchCard uses on the Résumé Match
 * page, kept local here rather than shared since the two pages' extra data
 * (skill checklist vs. similarity + overlap) differ. */
// Three-tier read of match.similarity_level (backend/nlp/recommend.py:
// check_uniqueness) — relative to the ProjectMind catalogue only, never a
// claim of global uniqueness. Omitted entirely for older cached results with
// no similarity_level rather than guessed.
const SIMILARITY_LEVEL_LABEL = {
  high: 'Highly similar',
  moderate: 'Moderately similar',
  low: 'Low similarity',
}

function SimilarProjectCard({ match, isFavorite, onToggleFavorite, index, busyKind, onSelect, onCompare }) {
  const percent = Math.round((match.similarity ?? 0) * 100)
  const levelLabel = SIMILARITY_LEVEL_LABEL[match.similarity_level]
  return (
    <div className="flex flex-col">
      <ProjectCard project={match} isFavorite={isFavorite} onToggleFavorite={onToggleFavorite} index={index} />
      <div className="glass-panel -mt-2 p-4" style={{ borderRadius: 8 }}>
        <div className="flex items-center gap-3">
          <div className="h-1.5 flex-1 overflow-hidden rounded-full" style={{ background: 'var(--surface-container-high)' }}>
            <div className="h-full rounded-full" style={{ background: 'var(--primary)', width: `${percent}%` }} />
          </div>
          <span className="t-label-mono shrink-0 tabular-nums" style={{ color: 'var(--on-surface)', fontSize: 12 }}>
            {percent}% similar
          </span>
        </div>
        {levelLabel && (
          <p className="t-label-mono mt-1" style={{ color: 'var(--outline)', fontSize: 10.5 }}>
            {levelLabel} · relative to the ProjectMind catalogue
          </p>
        )}
        <div className="mt-3 flex flex-wrap gap-2">
          <Link
            to={`/project/${match.project_id}`}
            className="btn-secondary t-label-caps px-3 py-1.5"
            style={{ fontSize: 10.5 }}
          >
            View Project
          </Link>
          <button
            type="button"
            onClick={() => onSelect(match)}
            disabled={Boolean(busyKind)}
            className="btn-primary t-label-caps px-3 py-1.5 disabled:opacity-60"
            style={{ fontSize: 10.5 }}
          >
            {busyKind === 'select' ? 'Selecting…' : 'Select Project'}
          </button>
          <button
            type="button"
            onClick={() => onCompare(match)}
            disabled={Boolean(busyKind)}
            className="t-label-caps px-3 py-1.5 transition hover:opacity-80 disabled:opacity-60"
            style={{ border: '1px solid var(--border-technical)', color: 'var(--on-surface-variant)', borderRadius: 6, fontSize: 10.5 }}
          >
            {busyKind === 'compare' ? 'Opening…' : 'Compare'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default function UniquenessCheck() {
  const navigate = useNavigate()
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [domain, setDomain] = useState('')
  const [technologies, setTechnologies] = useState('')
  const [domains, setDomains] = useState([])
  const [status, setStatus] = useState('idle')
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)
  const [actionBusy, setActionBusy] = useState(null) // { projectId, kind } | null
  const [actionError, setActionError] = useState(null)
  const { isFavorite, toggle } = useFavorites()

  useEffect(() => {
    api.filters().then(({ data }) => setDomains(data.domains ?? [])).catch(() => {})
  }, [])

  // Domain/technologies are optional context, not new backend parameters —
  // check_uniqueness() already embeds title+description as one piece of
  // text, so folding these hints in gives the same similarity engine a
  // richer signal instead of inventing a second code path for them.
  const check = async () => {
    if (!title.trim() && !description.trim()) {
      setError('Describe your project idea below.')
      return
    }
    setStatus('loading')
    setError(null)
    const hint = [domain && `Domain: ${domain}.`, technologies.trim() && `Technologies: ${technologies.trim()}.`]
      .filter(Boolean)
      .join(' ')
    const fullDescription = [hint, description.trim()].filter(Boolean).join(' ')
    const techList = technologies.split(',').map((t) => t.trim()).filter(Boolean)
    try {
      const { data } = await api.uniqueness(title, fullDescription, domain, techList)
      setResult(data)
      setStatus('done')
    } catch (err) {
      setError(err.message)
      setStatus('error')
    }
  }

  // Same handoff Résumé Match uses: a fresh conversation, the project
  // selected via the exact endpoint the chat's own Select Project button
  // calls, then Dashboard (which already knows how to show the banner and,
  // for Compare, auto-send its own action-chip prompt).
  const startWorkflow = async (match, kind) => {
    setActionBusy({ projectId: match.project_id, kind })
    setActionError(null)
    try {
      const { data } = await api.createConversation()
      await api.selectProject(data.conversation_id, match.project_id)
      const params = new URLSearchParams({ c: data.conversation_id })
      if (kind === 'compare') params.set('autosend', 'Compare')
      navigate(`/dashboard?${params.toString()}`)
    } catch (err) {
      setActionError(err.message)
      setActionBusy(null)
    }
  }

  return (
    <div className="mx-auto max-w-6xl px-6 py-14">
      <PageHeader
        title="Is your project idea original?"
        description="Describe your own idea and we'll check it against the catalogue by meaning, so a reworded version of an existing project is still caught."
      />

      <div className="grid gap-6 lg:grid-cols-[340px_1fr]">
        <aside className="lg:sticky lg:top-20 lg:self-start">
          <Panel icon="fingerprint" title="Describe your idea" compact>
            <div className="space-y-4">
              <div>
                <label className="t-label-caps mb-1.5 block" style={{ color: 'var(--outline)', fontSize: 10 }}>
                  Project title
                </label>
                <input
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="AI-based student attendance system"
                  className="gm-input w-full px-3 py-2 text-sm"
                />
              </div>

              <div>
                <label className="t-label-caps mb-1.5 block" style={{ color: 'var(--outline)', fontSize: 10 }}>
                  What does it do?
                </label>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  rows={6}
                  placeholder="Describe the idea in your own words…"
                  className="gm-input w-full px-3 py-2 text-sm"
                />
              </div>

              <div>
                <label className="t-label-caps mb-1.5 block" style={{ color: 'var(--outline)', fontSize: 10 }}>
                  Domain (optional)
                </label>
                <select value={domain} onChange={(e) => setDomain(e.target.value)} className="gm-input w-full px-3 py-2 text-sm">
                  <option value="">Not specified</option>
                  {domains.map((d) => (
                    <option key={d} value={d}>{d}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="t-label-caps mb-1.5 block" style={{ color: 'var(--outline)', fontSize: 10 }}>
                  Technologies (optional)
                </label>
                <input
                  value={technologies}
                  onChange={(e) => setTechnologies(e.target.value)}
                  placeholder="Python, OpenCV, Flask"
                  className="gm-input w-full px-3 py-2 text-sm"
                />
              </div>

              <button onClick={check} disabled={status === 'loading'} className="btn-primary t-label-caps w-full px-4 py-2">
                {status === 'loading' ? 'Checking…' : 'Check originality'}
              </button>

              {error && <p className="t-body-md" style={{ color: '#ffb4ab', fontSize: 13 }}>{error}</p>}

              <p className="t-label-mono" style={{ color: 'var(--outline)', fontSize: 11 }}>
                Checked by meaning against the same catalogue search uses — nothing you enter is stored.
              </p>
            </div>
          </Panel>
        </aside>

        <section>
          {status === 'idle' && (
            <EmptyState title="Describe an idea to get started" hint="Fill in the form on the left, then check its originality." />
          )}
          {status === 'loading' && <Spinner label="Comparing your idea against the catalogue…" />}
          {status === 'error' && <ErrorNotice message={error} onRetry={check} />}

          {status === 'done' && result && (
            <>
              <div
                className="glass-panel mb-5 p-5"
                style={{ borderRadius: 8, border: `1px solid ${result.is_unique ? 'var(--border-technical)' : 'var(--primary)'}` }}
              >
                <div className="flex items-baseline gap-3">
                  <span className="t-headline-lg" style={{ color: 'var(--primary)' }}>
                    {result.originality_score}%
                  </span>
                  <span className="t-label-mono" style={{ color: 'var(--on-surface-variant)' }}>
                    {result.is_unique ? 'Looks original' : 'Project originality'}
                  </span>
                </div>
                <p className="t-body-md mt-1.5" style={{ color: 'var(--outline)', fontSize: 12.5 }}>
                  {result.is_unique
                    ? 'No catalogue project is close enough by meaning to flag.'
                    : `Closest match scored ${Math.round(result.highest_similarity * 100)}% similarity (flagged above ${Math.round(result.threshold * 100)}%).`}
                </p>

                {result.overlapping_concepts?.length > 0 && (
                  <div className="mt-4">
                    <p className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>Overlapping concepts</p>
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      {result.overlapping_concepts.map((c) => (
                        <span key={c} className="gm-chip px-2 py-1">{c}</span>
                      ))}
                    </div>
                  </div>
                )}

                {result.suggestions?.length > 0 && (
                  <div className="mt-4">
                    <p className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>Making it more unique</p>
                    <ul className="t-body-md mt-1.5 space-y-1" style={{ color: 'var(--on-surface-variant)', fontSize: 12.5 }}>
                      {result.suggestions.map((s) => (
                        <li key={s}>· {s}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>

              {result.getting_started && (
                <div className="mb-5">
                  <GettingStartedPanel plan={result.getting_started} />
                </div>
              )}

              {actionError && (
                <p className="t-body-md mb-3" style={{ color: '#ffb4ab', fontSize: 13 }}>{actionError}</p>
              )}

              {result.similar_projects.length === 0 ? (
                <EmptyState title="No similar projects found" hint="Your idea doesn't closely match anything in the catalogue yet." />
              ) : (
                <div className="grid gap-4 sm:grid-cols-2">
                  {result.similar_projects.map((match, index) => (
                    <SimilarProjectCard
                      key={match.project_id}
                      match={match}
                      index={index}
                      isFavorite={isFavorite(match.project_id)}
                      onToggleFavorite={toggle}
                      busyKind={actionBusy?.projectId === match.project_id ? actionBusy.kind : null}
                      onSelect={(m) => startWorkflow(m, 'select')}
                      onCompare={(m) => startWorkflow(m, 'compare')}
                    />
                  ))}
                </div>
              )}
            </>
          )}
        </section>
      </div>
    </div>
  )
}
