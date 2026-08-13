import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { motion } from 'framer-motion'
import api from '../services/api'
import useFavorites from '../hooks/useFavorites'
import useAuth from '../hooks/useAuth.jsx'
import ProjectCard from '../components/ProjectCard'
import ProjectPlanner from '../components/ProjectPlanner'
import TeamBuilder from '../components/TeamBuilder'
import ProjectChat from '../components/ProjectChat'
import FeedbackForm from '../components/FeedbackForm'
import { Spinner, ErrorNotice } from '../components/Feedback'
import Panel from '../components/Panel'

/**
 * Distinct from <TeamBuilder>: that one suggests roles from skills you type
 * in, stateless, no account needed. This creates a persistent, joinable
 * workspace (backend/teams/service.py) for people who actually want to
 * message each other about the project — hence the account requirement.
 */
function StartTeamWorkspace({ project }) {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  if (!user) {
    return (
      <Panel icon="groups" title="Team workspace" description="Sign in to start a shared team workspace for this project — an invite code, member list, and a message board.">
        <Link to="/account" className="btn-primary t-label-caps inline-block px-4 py-2">
          Sign in
        </Link>
      </Panel>
    )
  }

  const start = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const { data } = await api.createTeam(project.project_id, name)
      navigate(`/teams/${data.team_id}`)
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  return (
    <Panel icon="groups" title="Team workspace" description="Start a shared space for this project — an invite code your teammates can join with, and a message board.">
      <form onSubmit={start} className="flex gap-2">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={`${project.title} team`}
          className="gm-input flex-1 px-3 py-2 text-sm"
        />
        <button type="submit" disabled={busy} className="btn-primary t-label-caps shrink-0 px-4 py-2">
          {busy ? 'Starting…' : 'Start team'}
        </button>
      </form>
      {error && <p className="t-body-md mt-2" style={{ color: '#ffb4ab', fontSize: 13 }}>{error}</p>}
    </Panel>
  )
}

// Anchors into the sections already on this page — added because the page
// grew long enough (overview, skill gap, planner, team, chat, similar) that
// jumping straight to one is worth a click, not a rebuild of any of them.
const WORKSPACE_SECTIONS = [
  { id: 'overview', label: 'Overview' },
  { id: 'skill-gap', label: 'Skill Gap' },
  { id: 'plan', label: 'Synopsis & Roadmap' },
  { id: 'team', label: 'Team' },
  { id: 'mentor', label: 'AI Mentor' },
  { id: 'similar', label: 'Similar' },
]

function WorkspaceNav() {
  return (
    <nav className="sticky top-0 z-10 -mx-6 flex gap-1 overflow-x-auto px-6 py-2 backdrop-blur-sm" style={{ background: 'color-mix(in srgb, var(--background) 92%, transparent)', borderBottom: '1px solid var(--border-technical)' }}>
      {WORKSPACE_SECTIONS.map((s) => (
        <a
          key={s.id}
          href={`#${s.id}`}
          className="t-label-mono shrink-0 whitespace-nowrap px-3 py-1.5 transition hover:opacity-75"
          style={{ color: 'var(--on-surface-variant)', fontSize: 12 }}
        >
          {s.label}
        </a>
      ))}
    </nav>
  )
}

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

function SkillGap({ projectId }) {
  const [input, setInput] = useState('')
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)

  const analyse = async () => {
    const skills = input.split(',').map((s) => s.trim()).filter(Boolean)
    if (!skills.length) return
    setBusy(true)
    try {
      const { data } = await api.skillGap(projectId, skills)
      setResult(data)
    } catch {
      setResult(null)
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

export default function ProjectDetail() {
  const { id } = useParams()
  const [project, setProject] = useState(null)
  const [similar, setSimilar] = useState([])
  const [status, setStatus] = useState('loading')
  const [error, setError] = useState(null)
  const { isFavorite, toggle } = useFavorites()

  useEffect(() => {
    let cancelled = false
    setStatus('loading')

    // Similar projects are secondary — if that call fails the page should
    // still render the project itself, so it is settled separately.
    Promise.all([api.getProject(id), api.similar(id, 4).catch(() => ({ data: [] }))])
      .then(([projectResponse, similarResponse]) => {
        if (cancelled) return
        setProject(projectResponse.data)
        setSimilar(similarResponse.data)
        setStatus('done')
      })
      .catch((err) => {
        if (cancelled) return
        setError(err.message)
        setStatus('error')
      })

    return () => {
      cancelled = true
    }
  }, [id])

  // Jumps to a section anchor once its content has actually rendered —
  // needed because a route change (e.g. ProjectCard's "Find Similar" button
  // linking to /project/<id>#similar) doesn't trigger the browser's native
  // same-document anchor scroll the way an in-page <a href="#..."> does
  // (WorkspaceNav above); the target section also doesn't exist in the DOM
  // until `similar` finishes loading.
  useEffect(() => {
    if (status !== 'done') return
    const hash = window.location.hash.slice(1)
    if (!hash) return
    document.getElementById(hash)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [status])

  if (status === 'loading') return <div className="mx-auto max-w-6xl px-6 py-14"><Spinner label="Loading project…" /></div>
  if (status === 'error') return <div className="mx-auto max-w-6xl px-6 py-14"><ErrorNotice message={error} /></div>

  const favorited = isFavorite(project.project_id)

  return (
    <div className="mx-auto max-w-6xl space-y-6 px-6 py-14">
      <Link
        to="/"
        className="t-label-mono inline-flex items-center gap-1.5 transition hover:opacity-75"
        style={{ color: 'var(--on-surface-variant)' }}
      >
        <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
        </svg>
        Back to search
      </Link>

      <WorkspaceNav />

      <motion.header id="overview" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
        className="glass-panel p-6 sm:p-8" style={{ borderRadius: 8 }}>
        <div className="flex items-start justify-between gap-4">
          <h1 className="t-headline-lg" style={{ color: 'var(--primary)', fontSize: 28 }}>{project.title}</h1>
          <div className="flex shrink-0 items-center gap-2">
          {project.github_url && (
            <a
              href={project.github_url}
              target="_blank"
              rel="noreferrer"
              className="t-label-caps inline-flex items-center gap-1.5 px-3 py-2 transition hover:bg-white/5"
              style={{ border: '1px solid var(--border-technical)', color: 'var(--on-surface-variant)', borderRadius: 8 }}
            >
              <svg className="h-4 w-4" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                <path d="M12 2A10 10 0 002 12c0 4.42 2.87 8.17 6.84 9.5.5.09.68-.22.68-.48l-.01-1.7c-2.78.6-3.37-1.34-3.37-1.34-.46-1.16-1.11-1.47-1.11-1.47-.91-.62.07-.6.07-.6 1 .07 1.53 1.03 1.53 1.03.9 1.53 2.34 1.09 2.91.83.09-.65.35-1.09.63-1.34-2.22-.25-4.56-1.11-4.56-4.94 0-1.09.39-1.98 1.03-2.68-.1-.25-.45-1.27.1-2.65 0 0 .84-.27 2.75 1.02a9.6 9.6 0 015 0c1.91-1.29 2.75-1.02 2.75-1.02.55 1.38.2 2.4.1 2.65.64.7 1.03 1.59 1.03 2.68 0 3.84-2.34 4.69-4.57 4.94.36.31.68.92.68 1.85l-.01 2.75c0 .27.18.58.69.48A10 10 0 0022 12 10 10 0 0012 2z" />
              </svg>
              Reference repo
            </a>
          )}
          <button
            onClick={() => toggle(project.project_id)}
            className="t-label-caps shrink-0 px-3 py-2 transition"
            style={
              favorited
                ? { border: '1px solid var(--primary)', color: 'var(--primary)', borderRadius: 8 }
                : { border: '1px solid var(--border-technical)', color: 'var(--on-surface-variant)', borderRadius: 8 }
            }
          >
            {favorited ? '★ Saved' : '☆ Save'}
          </button>
          </div>
        </div>

        <div className="t-label-mono mt-3 flex flex-wrap items-center gap-x-2.5 gap-y-1" style={{ color: 'var(--on-surface-variant)' }}>
          <span>{project.domain}</span>
          <span style={{ color: 'var(--border-technical)' }}>·</span>
          <span>{project.difficulty}</span>
          <span style={{ color: 'var(--border-technical)' }}>·</span>
          <span>{project.duration_weeks} weeks</span>
        </div>

        <p className="t-body-md mt-5" style={{ color: 'var(--on-surface)' }}>{project.description}</p>

        <div className="mt-6 grid gap-6 pt-6 sm:grid-cols-2" style={{ borderTop: '1px solid var(--border-technical)' }}>
          <div>
            <h2 className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>Technologies</h2>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {project.technologies.map((t) => (
                <span key={t} className="gm-chip px-2 py-1">
                  {t}
                </span>
              ))}
            </div>
          </div>
          <div>
            <h2 className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>Skills required</h2>
            <ul className="t-body-md mt-2 space-y-1" style={{ color: 'var(--on-surface-variant)' }}>
              {project.skills.map((s) => <li key={s}>• {s}</li>)}
            </ul>
          </div>
        </div>

        {project.learning_resources?.length > 0 && (
          <div className="mt-6 pt-6" style={{ borderTop: '1px solid var(--border-technical)' }}>
            <h2 className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>Learning resources</h2>
            <ul className="mt-2 space-y-1">
              {project.learning_resources.map((url) => (
                <li key={url}>
                  <a href={url} target="_blank" rel="noreferrer"
                    className="t-body-md break-all transition hover:opacity-75" style={{ color: 'var(--on-surface-variant)', fontSize: 13 }}>
                    {url}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        )}
      </motion.header>

      <div id="skill-gap">
        <SkillGap projectId={project.project_id} />
      </div>

      <div id="plan">
        <ProjectPlanner projectId={project.project_id} />
      </div>

      <div id="team" className="space-y-6">
        <TeamBuilder projectId={project.project_id} />
        <StartTeamWorkspace project={project} />
      </div>

      <div id="mentor">
        <ProjectChat projectId={project.project_id} />
      </div>

      {/* Keyed to the project, so the stored row is labelled data rather than
          an anonymous comment. */}
      <FeedbackForm
        projectId={project.project_id}
        title="Was this a good recommendation?"
        hint="Rate how well this project matched what you were looking for."
      />

      {similar.length > 0 && (
        <section id="similar">
          <div className="mb-4 pb-3" style={{ borderBottom: '1px solid var(--border-technical)' }}>
            <h2 className="t-label-mono" style={{ color: 'var(--primary)', fontSize: 15 }}>
              Similar projects
            </h2>
            <p className="t-body-md mt-1" style={{ color: 'var(--on-surface-variant)', fontSize: 13 }}>
              Projects with similar concepts, technologies, or implementation patterns.
            </p>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            {similar.map((p, i) => (
              <ProjectCard
                key={p.project_id}
                project={p}
                index={i}
                isFavorite={isFavorite(p.project_id)}
                onToggleFavorite={toggle}
              />
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
