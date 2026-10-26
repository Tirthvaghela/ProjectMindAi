import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import api from '../services/api'
import useAuth from '../hooks/useAuth.jsx'
import useProfile from '../hooks/useProfile'
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
// Mirrors the backend's notion of a usable profile (profiles/personalization.py):
// something the recommender can act on, not merely an onboarding dismissal.
function profileHasSignals(profile) {
  if (!profile) return false
  const a = profile.availability || {}
  return Boolean(profile.skills.length || profile.interests.length || profile.experience.length || a.hours_per_week || a.max_project_weeks)
}

const REASON_TEXT = {
  sign_in_required: 'Sign in to use your saved profile.',
  no_profile: 'You have no saved profile yet, so these are not personalised.',
  nothing_usable: 'Your profile has nothing the recommender can use yet.',
}

export default function RecommendedForYou({ isFavorite, onToggleFavorite }) {
  const [open, setOpen] = useState(false)
  const { user } = useAuth()
  const { profile } = useProfile()
  const profileUsable = Boolean(user) && profileHasSignals(profile)
  // On by default whenever there is a profile to use; the user can switch it
  // off to see the plain, skills-only ranking.
  const [useProfileSignals, setUseProfileSignals] = useState(true)
  const applyProfile = profileUsable && useProfileSignals
  const [personalization, setPersonalization] = useState(null)
  const [difficulties, setDifficulties] = useState([])
  const [skillsInput, setSkillsInput] = useState('')
  const [experienceLevel, setExperienceLevel] = useState('')
  const [teamSize, setTeamSize] = useState(1)
  const [maxWeeks, setMaxWeeks] = useState('')
  const [status, setStatus] = useState('idle') // idle | loading | done | error
  const [error, setError] = useState(null)
  const [results, setResults] = useState([])
  const [diagnostics, setDiagnostics] = useState(null)
  const [excludedUnknown, setExcludedUnknown] = useState(0)
  // The exact inputs the displayed results were computed from — compared with
  // the live form to tell when the cards on screen are for an older request.
  const [lastRun, setLastRun] = useState(null)
  // Only the newest request may write results: an older, slower response must
  // not overwrite a newer one.
  const requestId = useRef(0)

  const parsedSkills = skillsInput.split(',').map((s) => s.trim()).filter(Boolean)
  const currentRun = JSON.stringify({
    skills: parsedSkills,
    experience: experienceLevel,
    team: String(teamSize).trim(),
    weeks: String(maxWeeks).trim(),
    // A saved profile change must mark on-screen results as out of date too.
    profile: applyProfile ? profile?.updated_at ?? 'none' : 'off',
  })
  const stale = status === 'done' && lastRun?.signature !== currentRun

  useEffect(() => {
    if (!open || difficulties.length) return
    api
      .filters()
      .then(({ data }) => setDifficulties(data.difficulties ?? []))
      .catch(() => {
        /* The experience-level select just falls back to free entry-less "Any" if this fails. */
      })
  }, [open, difficulties.length])

  const fail = (message) => {
    setStatus('error')
    setError(message)
  }

  const run = async (event) => {
    event.preventDefault()
    // A disabled submit button already blocks a second click and Enter, but
    // the handler is the real guard.
    if (status === 'loading') return

    const known_skills = parsedSkills
    if (!known_skills.length && !applyProfile) return fail('Add at least one skill, separated by commas.')

    const team = Number(teamSize)
    if (!Number.isInteger(team) || team < 1 || team > 20) return fail('Team size must be a whole number from 1 to 20.')

    const weeksText = String(maxWeeks).trim()
    const weeks = weeksText === '' ? undefined : Number(weeksText)
    if (weeks !== undefined && (!Number.isInteger(weeks) || weeks < 1 || weeks > 52)) {
      return fail('Max weeks must be a whole number from 1 to 52, or left empty for no limit.')
    }

    const id = ++requestId.current
    setStatus('loading')
    setError(null)
    try {
      const response = await api.recommend({
        known_skills,
        experience_level: experienceLevel || undefined,
        team_size: team,
        max_duration_weeks: weeks,
        top_k: 6,
        ...(applyProfile ? { use_profile: true } : {}),
      })
      if (id !== requestId.current) return
      setResults(response.data)
      setDiagnostics(response.diagnostics ?? null)
      setExcludedUnknown(response.excluded_unknown_duration ?? 0)
      setPersonalization(response.personalization ?? null)
      setLastRun({ signature: currentRun, experience: experienceLevel, team, weeks })
      setStatus('done')
    } catch (err) {
      if (id !== requestId.current) return
      setResults([])
      setError(err.message)
      setStatus('error')
    }
  }

  const emptyMessage = () => {
    const parts = []
    if (lastRun?.weeks) {
      parts.push(`Nothing fits within ${lastRun.weeks} week${lastRun.weeks === 1 ? '' : 's'} for a team of ${lastRun.team}${lastRun.experience ? ` at ${lastRun.experience} level` : ''}.`)
      if (diagnostics?.shortest_estimated_weeks != null) {
        parts.push(`The shortest project in the catalogue is estimated at about ${diagnostics.shortest_estimated_weeks} weeks for that setup — raise the limit or add teammates.`)
      }
    } else {
      parts.push(personalization?.applied ? 'No projects matched your profile and inputs.' : 'No projects matched those skills.')
    }
    return parts.join(' ')
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
                {applyProfile ? 'Extra skills for this search (optional)' : 'Your skills'}
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

          {user && (
            <div className="mt-3" style={{ borderTop: '1px solid var(--border-technical)', paddingTop: 12 }}>
              {profileUsable ? (
                <label className="flex items-start gap-2" style={{ color: 'var(--on-surface)', fontSize: 13 }}>
                  <input
                    type="checkbox"
                    checked={useProfileSignals}
                    onChange={(e) => setUseProfileSignals(e.target.checked)}
                    className="mt-1"
                  />
                  <span>
                    Use my saved profile
                    <span className="block" style={{ color: 'var(--on-surface-variant)', fontSize: 12 }}>
                      Your skills, interests and time limits are added to this search. <Link to="/profile" className="underline">Update profile</Link>
                    </span>
                  </span>
                </label>
              ) : (
                <p className="t-body-md" style={{ color: 'var(--on-surface-variant)', fontSize: 12.5 }}>
                  Want picks tailored to you? <Link to="/profile?setup=1" className="underline" style={{ color: 'var(--primary)' }}>Add your skills and interests</Link> — optional.
                </p>
              )}
            </div>
          )}

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
                aria-describedby="recommend-weeks-hint"
                className="gm-input w-full px-2 py-2 text-sm"
              />
              <p id="recommend-weeks-hint" className="t-body-md mt-1" style={{ color: 'var(--outline)', fontSize: 11 }}>
                Compared with the estimate for your team size and experience.
              </p>
            </div>
          </div>

          {status === 'loading' && (
            <p className="t-body-md mt-4" role="status" style={{ color: 'var(--outline)', fontSize: 13 }}>
              Ranking the catalogue for your inputs…
            </p>
          )}

          {status === 'error' && error && (
            <p className="t-body-md mt-3" role="alert" style={{ color: '#ffb4ab', fontSize: 13 }}>{error}</p>
          )}

          {status === 'done' && (
            <>
              <p className="t-label-mono mt-4" style={{ color: 'var(--on-surface-variant)', fontSize: 12 }}>
                Results for {lastRun?.experience || 'any experience level'} · team of {lastRun?.team}
                {lastRun?.weeks ? ` · up to ${lastRun.weeks} weeks` : ' · no week limit'}
              </p>
              {personalization?.applied ? (
                <p className="t-body-md mt-2" role="status" style={{ color: 'var(--on-surface-variant)', fontSize: 12.5 }}>
                  Personalised with your profile: {personalization.skills_from_profile} skill{personalization.skills_from_profile === 1 ? '' : 's'}
                  {personalization.interests.length ? `, ${personalization.interests.length} interest${personalization.interests.length === 1 ? '' : 's'}` : ''}
                  {personalization.preferred_weeks ? `, preferred length ${personalization.preferred_weeks} weeks` : ''}
                  {personalization.experience_level_source === 'profile_skill_levels' ? `. Experience level (${personalization.experience_level}) is estimated from your own skill ratings — pick one above to override` : ''}.
                  {' '}<Link to="/profile" className="underline">Edit profile</Link>
                </p>
              ) : (
                personalization && (
                  <p className="t-body-md mt-2" style={{ color: 'var(--outline)', fontSize: 12.5 }}>{REASON_TEXT[personalization.reason] ?? 'Your profile was not used.'}</p>
                )
              )}
              {excludedUnknown > 0 && (
                <p className="t-body-md mt-2" style={{ color: 'var(--outline)', fontSize: 12 }}>
                  {excludedUnknown} project{excludedUnknown === 1 ? '' : 's'} with no documented duration {excludedUnknown === 1 ? 'was' : 'were'} left out, because {excludedUnknown === 1 ? 'it' : 'they'} can’t be confirmed to fit your week limit.
                </p>
              )}
              {stale && (
                <p className="t-body-md mt-2" role="status" style={{ color: '#ffb4ab', fontSize: 12.5 }}>
                  You changed the inputs — these results are for the previous request. Press “Find my best fit” to update them.
                </p>
              )}
              {results.length === 0 ? (
                <p className="t-body-md mt-3" style={{ color: 'var(--outline)', fontSize: 13 }}>{emptyMessage()}</p>
              ) : (
                <div className="mt-4 grid gap-4 sm:grid-cols-2" style={{ opacity: stale ? 0.45 : 1 }} aria-busy={stale}>
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
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}
