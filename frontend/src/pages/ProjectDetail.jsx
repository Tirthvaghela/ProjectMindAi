import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { motion } from 'framer-motion'
import api from '../services/api'
import useFavorites from '../hooks/useFavorites'
import ProjectCard from '../components/ProjectCard'
import ProjectPlanner from '../components/ProjectPlanner'
import SkillGapPanel from '../components/SkillGapPanel'
import PersonalSkillGap from '../components/PersonalSkillGap'
import LearningRoadmap from '../components/LearningRoadmap'
import TeamBuilder from '../components/TeamBuilder'
import TeamFormation from '../components/TeamFormation'
import StartTeamWorkspace from '../components/StartTeamWorkspace'
import ProjectChat from '../components/ProjectChat'
import FeedbackForm from '../components/FeedbackForm'
import WorkspaceNav from '../components/WorkspaceNav'
import { Spinner, ErrorNotice } from '../components/Feedback'

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
        to="/dashboard"
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

      <div id="skill-gap" className="space-y-6">
        <PersonalSkillGap projectId={project.project_id} />
        <LearningRoadmap projectId={project.project_id} />
        <SkillGapPanel onCheck={(skills) => api.skillGap(project.project_id, skills)} />
      </div>

      <div id="plan">
        <ProjectPlanner
          fetchers={{
            synopsis: () => api.synopsis(project.project_id),
            roadmap: () => api.roadmap(project.project_id),
            milestones: () => api.milestones(project.project_id),
            timeline: (params) => api.timelinePredict(project.project_id, params),
          }}
        />
      </div>

      <div id="team" className="space-y-6">
        <TeamFormation projectId={project.project_id} />
        <TeamBuilder onBuild={(members) => api.teamBuilder(project.project_id, members)} />
        <div id="start-team">
          <StartTeamWorkspace
            placeholderName={`${project.title} team`}
            onCreate={(name) => api.createTeam(project.project_id, name)}
          />
        </div>
      </div>

      <div id="mentor">
        <ProjectChat
          storageKey={`projectmind.chat.${project.project_id}`}
          onSend={(message, history) => api.chat(project.project_id, message, history)}
        />
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
