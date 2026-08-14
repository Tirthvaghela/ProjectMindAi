import { useEffect, useState } from 'react'
import api from '../services/api'
import ProjectCard from './ProjectCard'

/**
 * A dedicated, skill-driven ranking — POST /api/recommend
 * (backend/nlp/recommend.py:personalized_recommend) — distinct from the
 * query-driven search above it on this same page. Plain search already
 * explains *why* a result matched a query (ProjectCard's "why_recommended"
 * line); this is the one path that folds skill-gap fit and timeline fit
 * into the ranking *score* itself, not just the explanation, which is what
 * plain search — even with personalisation on — never does.
 *
 * Collapsed by default and deliberately not merged into the search
 * results/personalize toggle above: this needs its own inputs (skills,
 * experience, timeline) that don't fit that flow, and conflating "ranked by
 * query relevance" with "ranked by how ready you are to build it" would
 * make neither result set trustworthy.
 */
export default function RecommendedForYou({ isFavorite, onToggleFavorite }) {
  const [open, setOpen] = useState(false)
  const [difficulties, setDifficulties] = useState([])
  const [skillsInput, setSkillsInput] = useState('')
  const [experienceLevel, setExperienceLevel] = useState('')
  const [teamSize, setTeamSize] = useState(1)
  const [maxWeeks, setMaxWeeks] = useState('')
  const [status, setStatus] = useState('idle') // idle | loading | done | error
  const [error, setError] = useState(null)
  const [results, setResults] = useState([])

  useEffect(() => {
    if (!open || difficulties.length) return
    api
      .filters()
      .then(({ data }) => setDifficulties(data.difficulties ?? []))
      .catch(() => {
        /* The experience-level select just falls back to free entry-less "Any" if this fails. */
      })
  }, [open, difficulties.length])

  const run = async (event) => {
    event.preventDefault()
    const known_skills = skillsInput.split(',').map((s) => s.trim()).filter(Boolean)
    if (!known_skills.length) {
      setStatus('error')
      setError('Add at least one skill, separated by commas.')
      return
    }
    setStatus('loading')
    setError(null)
    try {
      const { data } = await api.recommend({
        known_skills,
        experience_level: experienceLevel || undefined,
        team_size: Number(teamSize) || 1,
        max_duration_weeks: maxWeeks ? Number(maxWeeks) : undefined,
        top_k: 6,
      })
      setResults(data)
      setStatus('done')
    } catch (err) {
      setError(err.message)
      setStatus('error')
    }
  }

  return (
    <div className="glass-panel mb-8 overflow-hidden" style={{ borderRadius: 8 }}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-3 p-5 text-left transition hover:opacity-90"
      >
        <div className="min-w-0">
          <p className="t-label-mono" style={{ color: 'var(--primary)', fontSize: 15 }}>Best fit for you</p>
          <p className="t-body-md mt-1" style={{ color: 'var(--on-surface-variant)', fontSize: 13 }}>
            Rank the catalogue by your skills, experience, and timeline — not just a search query.
          </p>
        </div>
        <span
          className="material-symbols-outlined shrink-0"
          style={{ color: 'var(--outline)', transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 0.15s' }}
          aria-hidden="true"
        >
          expand_more
        </span>
      </button>

      {open && (
        <div className="p-5 pt-0">
          <form onSubmit={run} className="grid gap-3 sm:grid-cols-[1fr_auto] sm:items-end">
            <div>
              <label className="t-label-caps mb-1.5 block" style={{ color: 'var(--outline)', fontSize: 10 }} htmlFor="recommend-skills">
                Your skills
              </label>
              <input
                id="recommend-skills"
                value={skillsInput}
                onChange={(e) => setSkillsInput(e.target.value)}
                placeholder="Python, React, pandas…"
                className="gm-input w-full px-3 py-2 text-sm"
              />
            </div>
            <button type="submit" disabled={status === 'loading'} className="btn-primary t-label-caps px-4 py-2">
              {status === 'loading' ? 'Ranking…' : 'Find my best fit'}
            </button>
          </form>

          <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
            <div>
              <label className="t-label-caps mb-1.5 block" style={{ color: 'var(--outline)', fontSize: 10 }} htmlFor="recommend-level">
                Experience
              </label>
              <select
                id="recommend-level"
                value={experienceLevel}
                onChange={(e) => setExperienceLevel(e.target.value)}
                className="gm-input w-full px-2 py-2 text-sm"
              >
                <option value="">Any</option>
                {difficulties.map((d) => (
                  <option key={d} value={d}>{d}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="t-label-caps mb-1.5 block" style={{ color: 'var(--outline)', fontSize: 10 }} htmlFor="recommend-team">
                Team size
              </label>
              <input
                id="recommend-team"
                type="number"
                min={1}
                max={20}
                value={teamSize}
                onChange={(e) => setTeamSize(e.target.value)}
                className="gm-input w-full px-2 py-2 text-sm"
              />
            </div>
            <div>
              <label className="t-label-caps mb-1.5 block" style={{ color: 'var(--outline)', fontSize: 10 }} htmlFor="recommend-weeks">
                Max weeks
              </label>
              <input
                id="recommend-weeks"
                type="number"
                min={1}
                max={52}
                value={maxWeeks}
                onChange={(e) => setMaxWeeks(e.target.value)}
                placeholder="Any"
                className="gm-input w-full px-2 py-2 text-sm"
              />
            </div>
          </div>

          {status === 'error' && error && (
            <p className="t-body-md mt-3" style={{ color: '#ffb4ab', fontSize: 13 }}>{error}</p>
          )}

          {status === 'done' && (
            results.length === 0 ? (
              <p className="t-body-md mt-4" style={{ color: 'var(--outline)', fontSize: 13 }}>
                No close matches for that combination — try fewer constraints.
              </p>
            ) : (
              <div className="mt-5 grid gap-4 sm:grid-cols-2">
                {results.map((project, index) => (
                  <ProjectCard
                    key={project.project_id}
                    project={project}
                    index={index}
                    isFavorite={isFavorite(project.project_id)}
                    onToggleFavorite={onToggleFavorite}
                  />
                ))}
              </div>
            )
          )}
        </div>
      )}
    </div>
  )
}
