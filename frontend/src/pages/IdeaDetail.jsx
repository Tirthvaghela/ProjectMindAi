import { useEffect } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { motion } from 'framer-motion'
import api from '../services/api'
import useFavorites from '../hooks/useFavorites'
import ProjectCard from '../components/ProjectCard'
import ProjectPlanner from '../components/ProjectPlanner'
import SkillGapPanel from '../components/SkillGapPanel'
import TeamBuilder from '../components/TeamBuilder'
import StartTeamWorkspace from '../components/StartTeamWorkspace'
import ProjectChat from '../components/ProjectChat'
import WorkspaceNav from '../components/WorkspaceNav'
import { EmptyState } from '../components/Feedback'

/**
 * The full workspace for an AI-GENERATED idea — the idea-scoped mirror of
 * pages/ProjectDetail.jsx, reached by clicking an idea's name on
 * GeneratedIdeaCard (Ideate.jsx / Dashboard.jsx). Same six sections
 * (Overview, Skill Gap, Synopsis & Roadmap, Team, AI Mentor, Similar), same
 * shared components ProjectDetail.jsx itself uses (SkillGapPanel,
 * ProjectPlanner, TeamBuilder, ProjectChat) — each just wired to
 * backend/routes/ideas.py's idea-scoped endpoints instead of a project_id,
 * since a generated idea is deliberately never written to Mongo (see
 * nlp/ai_assistant.py's module docstring).
 *
 * Because of that, there is no ID to fetch this page's data by — the idea
 * arrives entirely through React Router navigation state
 * (`navigate('/idea', { state: { idea } })`, see GeneratedIdeaCard.jsx). A
 * hard refresh or a direct link loses that state, so this page shows a
 * plain "not available" empty state rather than erroring in that case.
 */
export default function IdeaDetail() {
  const location = useLocation()
  const idea = location.state?.idea
  const { isFavorite, toggle } = useFavorites()

  // Same "jump to the section a caller linked to" behaviour ProjectDetail.jsx
  // has — needed because this page can also be reached with a #hash (see
  // GeneratedIdeaCard's title link) and the target section only exists in
  // the DOM once `idea` itself has rendered.
  useEffect(() => {
    if (!idea) return
    const hash = window.location.hash.slice(1)
    if (!hash) return
    document.getElementById(hash)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [idea])

  if (!idea) {
    return (
      <div className="mx-auto max-w-6xl px-6 py-14">
        <EmptyState
          title="This idea isn't available anymore"
          hint="Generated ideas aren't saved on the server — reopen or regenerate it from the Ideation workspace to see its workspace again."
        >
          <Link to="/ideate" className="btn-primary t-label-caps inline-block px-4 py-2">
            Go to Ideate
          </Link>
        </EmptyState>
      </div>
    )
  }

  const closest = idea.similar_projects?.[0]

  return (
    <div className="mx-auto max-w-6xl space-y-6 px-6 py-14">
      <Link
        to="/ideate"
        className="t-label-mono inline-flex items-center gap-1.5 transition hover:opacity-75"
        style={{ color: 'var(--on-surface-variant)' }}
      >
        <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
        </svg>
        Back to Ideate
      </Link>

      <WorkspaceNav />

      <motion.header id="overview" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
        className="glass-panel p-6 sm:p-8" style={{ borderRadius: 8 }}>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <span
              className="t-label-caps inline-block px-2 py-1"
              style={{ background: 'var(--primary)', color: 'var(--on-primary)', borderRadius: 999, fontSize: 9.5 }}
            >
              AI Generated Project Idea
            </span>
            <h1 className="t-headline-lg mt-2.5" style={{ color: 'var(--primary)', fontSize: 28 }}>{idea.name}</h1>
          </div>
          {idea.originality_score != null && (
            <span
              className="t-label-mono shrink-0 tabular-nums"
              style={{ color: idea.is_unique ? 'var(--primary)' : 'var(--outline)', fontSize: 13 }}
            >
              {idea.originality_score}% original
            </span>
          )}
        </div>

        <div className="t-label-mono mt-3 flex flex-wrap items-center gap-x-2.5 gap-y-1" style={{ color: 'var(--on-surface-variant)' }}>
          <span>{idea.domain}</span>
          <span style={{ color: 'var(--border-technical)' }}>·</span>
          <span>{idea.difficulty}</span>
          <span style={{ color: 'var(--border-technical)' }}>·</span>
          <span>~{idea.duration_weeks} weeks</span>
        </div>

        <div className="mt-5 space-y-4">
          {idea.problem && (
            <div>
              <h2 className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>Problem</h2>
              <p className="t-body-md mt-1" style={{ color: 'var(--on-surface)' }}>{idea.problem}</p>
            </div>
          )}
          {idea.solution && (
            <div>
              <h2 className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>Solution</h2>
              <p className="t-body-md mt-1" style={{ color: 'var(--on-surface)' }}>{idea.solution}</p>
            </div>
          )}
          {idea.unique_point && (
            <div>
              <h2 className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>Why it's different</h2>
              <p className="t-body-md mt-1" style={{ color: 'var(--on-surface)' }}>{idea.unique_point}</p>
            </div>
          )}
        </div>

        {idea.technologies?.length > 0 && (
          <div className="mt-6 pt-6" style={{ borderTop: '1px solid var(--border-technical)' }}>
            <h2 className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>Technologies</h2>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {idea.technologies.map((t) => (
                <span key={t} className="gm-chip px-2 py-1">
                  {t}
                </span>
              ))}
            </div>
          </div>
        )}

        {closest && (
          <p className="t-label-mono mt-6 pt-6" style={{ color: 'var(--outline)', borderTop: '1px solid var(--border-technical)', fontSize: 11 }}>
            Closest existing project:{' '}
            <Link to={`/project/${closest.project_id}`} className="transition hover:opacity-75" style={{ color: 'var(--primary)' }}>
              {closest.title}
            </Link>
            {' '}({Math.round((closest.similarity ?? 0) * 100)}% similar)
          </p>
        )}
      </motion.header>

      <div id="skill-gap">
        <SkillGapPanel onCheck={(skills) => api.ideaSkillGap(idea, skills)} />
      </div>

      <div id="plan">
        <ProjectPlanner
          fetchers={{
            synopsis: () => api.ideaSynopsis(idea),
            roadmap: () => api.ideaRoadmap(idea),
            milestones: () => api.ideaMilestones(idea),
            timeline: (params) => api.ideaTimeline(idea, params),
          }}
        />
      </div>

      <div id="team" className="space-y-6">
        <TeamBuilder onBuild={(members) => api.ideaTeamBuilder(idea, members)} />
        <StartTeamWorkspace
          placeholderName={`${idea.name} team`}
          onCreate={(name) => api.createIdeaTeam(idea, name)}
        />
      </div>

      <div id="mentor">
        <ProjectChat
          storageKey={`projectmind.chat.idea.${idea.id || idea.name}`}
          onSend={(message, history) => api.ideaChat(idea, message, history)}
        />
      </div>

      {idea.similar_projects?.length > 0 && (
        <section id="similar">
          <div className="mb-4 pb-3" style={{ borderBottom: '1px solid var(--border-technical)' }}>
            <h2 className="t-label-mono" style={{ color: 'var(--primary)', fontSize: 15 }}>
              Similar projects
            </h2>
            <p className="t-body-md mt-1" style={{ color: 'var(--on-surface-variant)', fontSize: 13 }}>
              The closest existing catalogue projects to this idea, by meaning.
            </p>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            {idea.similar_projects.map((p, i) => (
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
