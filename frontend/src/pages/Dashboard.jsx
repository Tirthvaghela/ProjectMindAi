import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import useAuth from '../hooks/useAuth.jsx'
import useVoiceSearch from '../hooks/useVoiceSearch'
import api from '../services/api'
import MarkdownLite from '../components/MarkdownLite'
import { Spinner } from '../components/Feedback'
import AuthGateModal from '../components/AuthGateModal'
import GeneratedIdeaCard from '../components/GeneratedIdeaCard'
import { CopyButton, TypingDots } from '../components/ChatPrimitives'
import { clearPendingQuery, takePendingQuery } from '../utils/pendingQuery'

const STARTERS = [
  'Find an NLP project for 3 months',
  'Generate an original AI project',
  'Check if my project idea is unique',
  'Which project fits my skills?',
  'Create a roadmap for this project',
]

// Faint, fixed corner labels behind the empty-state — same "system is
// alive" texture the landing page uses, at a fraction of the opacity so it
// never competes with the actual quick-start content in front of it.
const BACKDROP_LABELS = [
  { text: 'HYBRID RETRIEVAL', style: { top: '8%', left: '4%' } },
  { text: 'AI REASONING', style: { top: '12%', right: '5%' } },
  { text: 'SEMANTIC SEARCH', style: { bottom: '14%', left: '6%' } },
  { text: 'PROJECT PLANNING', style: { bottom: '10%', right: '4%' } },
]
const BACKDROP_NODES = [
  { top: '18%', left: '10%' },
  { top: '22%', right: '12%' },
  { bottom: '20%', left: '14%' },
  { bottom: '24%', right: '9%' },
]

// Shown under the most recent assistant turn only when it recommended
// projects — quick ways to keep the same conversation going instead of
// retyping a full sentence, matching what the assistant's tools actually
// support (nlp/chat_tools.py: search again, or drill into one project).
const CONTEXTUAL_SUGGESTIONS = [
  'Show me easier ones',
  'Compare these',
  'Tell me more about the first one',
  'What technologies does it use?',
  'Create a roadmap for it',
]

// Shown once a project is selected (see ActiveProjectBanner) — each just
// sends natural language through the existing chat pipeline, letting the
// model's existing tools (nlp/chat_tools.py) do the work. No dedicated
// button wiring, no duplicated logic.
const PROJECT_ACTIONS = [
  { label: 'Compare', prompt: 'Compare this project with similar alternatives.' },
  { label: 'Check Skill Gap', prompt: 'Check my skill gap for this project.' },
  { label: 'Create Roadmap', prompt: 'Create a roadmap for this project.' },
  { label: 'Generate Synopsis', prompt: 'Generate the synopsis for this project.' },
  { label: 'Learning Path', prompt: "Show me a learning path for the skills I'm missing." },
  { label: 'Project Timeline', prompt: 'What is the estimated timeline for this project?' },
]

// Shown once a GENERATED idea is selected (see ActiveIdeaBanner) — the
// idea-context mirror of PROJECT_ACTIONS, adapted to the idea-specific tools
// (check_project_uniqueness/refine_project_idea/generate_idea_roadmap) since
// a generated idea has no project_id for the catalogue-only skill-gap/
// synopsis/timeline tools PROJECT_ACTIONS uses.
const IDEA_BUILD_ACTIONS = [
  { label: 'Check Uniqueness', prompt: 'Is this idea already available in your catalogue?' },
  { label: 'Compare', prompt: 'Compare this idea with the closest existing project.' },
  { label: 'Improve Idea', prompt: 'Make this idea more innovative.' },
  { label: 'Create Roadmap', prompt: 'Create a roadmap for this idea.' },
]

// Below this, a match is noise rather than signal — a purely conversational
// message ("explain REST vs GraphQL") still returns *a* top-k result from
// hybrid search, it just shouldn't be shown as if it were relevant.
const RELEVANCE_THRESHOLD = 0.3


/** Pulls the card list out of a stored/returned message's `blocks` — the
 * structured shape nlp/ai_assistant.py:general_reply attaches to a turn that
 * recommended projects, kept alongside `content` rather than rendered from
 * Markdown so cards survive independent of anything the model wrote. */
function projectsFromBlocks(blocks) {
  return blocks?.find((b) => b.type === 'project_recommendations')?.projects ?? []
}

function blockOfType(blocks, type) {
  return blocks?.find((b) => b.type === type) ?? null
}

/** "Which project/idea is this actually about" — a small connective label
 * for the follow-up result blocks (Feasibility, Scope, Resources, Timeline,
 * Milestones) that each already carry their own `project_id`/`title`
 * (backend/nlp/feasibility.py, timeline.py, generator.py all include them
 * in every result already, unused by the frontend until now). Reuses the
 * exact same badge wording DecisionCenterBlock's own eyebrow uses, so a
 * Scope/Resources/Feasibility result reads as one more stage of the SAME
 * plan Decision Center is the hub for — not an unrelated card — and stays
 * correct even scrolled back through history after the active
 * project/idea has since changed. Omitted entirely when a block predates
 * these fields (title missing) rather than showing a blank label. */
function BlockContextLabel({ projectId, title }) {
  if (!title) return null
  return (
    <div className="mb-2 flex items-center gap-1.5">
      {/* shrink-0 + whitespace-nowrap: without an explicit no-wrap, a flex
          item's automatic min-width is only its longest WORD, not the whole
          phrase — measured live at 390px, "Catalogue Project" wrapped to
          "Catalogue" / "Project" on two lines while fighting the truncating
          title span next to it for space. This keeps the badge on one line
          and lets the title alone absorb the shrink via its own truncate. */}
      <span className="gm-chip shrink-0 whitespace-nowrap px-1.5 py-0.5" style={{ fontSize: 8.5 }}>
        {projectId ? 'Catalogue Project' : 'AI-Generated Idea'}
      </span>
      <span className="t-label-mono truncate" style={{ color: 'var(--outline)', fontSize: 10.5 }}>
        {title}
      </span>
    </div>
  )
}

/** The [Select Project] action — a <button> nested in MiniProjectCard's
 * <Link>, so it needs the same preventDefault/stopPropagation pattern
 * ProjectCard.jsx's StarButton uses to avoid also triggering navigation. */
function SelectProjectButton({ project, selected, onSelect }) {
  return (
    <button
      onClick={(event) => {
        event.preventDefault()
        event.stopPropagation()
        onSelect(project)
      }}
      disabled={selected}
      className="t-label-caps mt-2 w-full px-2 py-1.5 transition disabled:opacity-100"
      style={
        selected
          ? { background: 'var(--primary)', color: 'var(--on-primary)', borderRadius: 6, fontSize: 10 }
          : { border: '1px solid var(--border-technical)', color: 'var(--on-surface-variant)', borderRadius: 6, fontSize: 10 }
      }
    >
      {selected ? 'Selected' : 'Select Project'}
    </button>
  )
}

function MatchBadge({ score }) {
  if (score == null) return null
  return (
    <span className="t-label-mono shrink-0" style={{ color: 'var(--primary)', fontSize: 11 }}>
      {Math.round(score * 100)}%
    </span>
  )
}

/** Compact matched/missing skill lines — only present on cards built from a
 * résumé/skill-aware result (nlp/chat_tools.py:match_resume_projects,
 * search_projects' personalized branch), so a plain catalogue search's cards
 * simply omit this block. Same have/missing vocabulary as SkillGapBlock,
 * capped to 3 each to keep a 240px card scannable. */
function SkillFitLines({ have, missing }) {
  if (!have?.length && !missing?.length) return null
  return (
    <div className="mt-1.5 space-y-0.5">
      {have?.length > 0 && (
        <p className="t-label-mono truncate" style={{ color: 'var(--on-surface-variant)', fontSize: 10.5 }}>
          ✓ {have.slice(0, 3).join(', ')}
        </p>
      )}
      {missing?.length > 0 && (
        <p className="t-label-mono truncate" style={{ color: 'var(--outline)', fontSize: 10.5 }}>
          ✗ {missing.slice(0, 3).join(', ')}
        </p>
      )}
    </div>
  )
}

function MiniProjectCard({ project, conversationId, selectedProjectId, onSelectProject }) {
  return (
    <div className="glass-panel card-hover flex shrink-0 flex-col p-3" style={{ width: 240, borderRadius: 8 }}>
      <Link
        to={`/project/${project.project_id}`}
        className="flex flex-1 flex-col"
        onClick={() => {
          // Clicking through to the project page is the obvious gesture for
          // "I want this one" — it shouldn't silently leave this
          // conversation without an active project just because the student
          // didn't separately hit [Select Project]. Marking it here means a
          // later "tell me more"-style follow-up back in this chat still
          // resolves to it via _active_project_note (nlp/ai_assistant.py),
          // instead of landing on ProjectDetail's own unrelated, stateless
          // chat widget with no memory of this conversation at all.
          if (conversationId && onSelectProject && project.project_id !== selectedProjectId) {
            onSelectProject(project)
          }
        }}
      >
        <div className="flex items-start justify-between gap-2">
          <p className="t-label-mono truncate" style={{ color: 'var(--primary)', fontSize: 13 }}>
            {project.title}
          </p>
          <MatchBadge score={project.match_score} />
        </div>
        <p className="t-label-mono mt-1" style={{ color: 'var(--outline)', fontSize: 11 }}>
          {project.difficulty} · {project.domain}
        </p>
        <p className="t-body-md mt-1.5 line-clamp-2" style={{ color: 'var(--on-surface-variant)', fontSize: 12, lineHeight: 1.4 }}>
          {project.description}
        </p>
        <SkillFitLines have={project.skills_you_have} missing={project.skills_to_learn} />
      </Link>
      {conversationId && onSelectProject && (
        <SelectProjectButton
          project={project}
          selected={project.project_id === selectedProjectId}
          onSelect={onSelectProject}
        />
      )}
    </div>
  )
}

/** [Compare] result — real fields only (see nlp/chat_tools.py:compare_projects),
 * a table rather than prose so numbers/lists stay scannable side by side. */
function ComparisonBlock({ block }) {
  const rows = [
    { label: 'Difficulty', get: (p) => p.difficulty },
    { label: 'Duration', get: (p) => `${p.duration_weeks} weeks` },
    { label: 'Technologies', get: (p) => p.technologies?.join(', ') },
    { label: 'Skills required', get: (p) => p.skills?.join(', ') },
    // Reuses the same catalogue nearest-neighbour signal the Decision Engine
    // shows (nlp/chat_tools.py:_uniqueness_percent) — omitted via '—' rather
    // than guessed when a project predates that field.
    { label: 'Uniqueness', get: (p) => (p.uniqueness_percent != null ? `${p.uniqueness_percent}%` : null) },
  ]
  return (
    <div className="glass-panel w-full max-w-full overflow-x-auto p-3" style={{ borderRadius: 8 }}>
      <table className="w-full text-left" style={{ borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            <th className="t-label-caps pb-2 pr-4" style={{ color: 'var(--outline)', fontSize: 10 }} />
            {block.projects.map((p) => (
              <th key={p.project_id} className="pb-2 pr-4 align-top">
                <Link to={`/project/${p.project_id}`} className="t-label-mono transition hover:opacity-75" style={{ color: 'var(--primary)', fontSize: 13 }}>
                  {p.title}
                </Link>
                {p.match_score != null && (
                  <div className="mt-0.5"><MatchBadge score={p.match_score} /></div>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.label} style={{ borderTop: '1px solid var(--border-technical)' }}>
              <td className="t-label-caps py-2 pr-4 align-top" style={{ color: 'var(--outline)', fontSize: 10, whiteSpace: 'nowrap' }}>
                {row.label}
              </td>
              {block.projects.map((p) => (
                <td key={p.project_id} className="t-body-md py-2 pr-4 align-top" style={{ color: 'var(--on-surface-variant)', fontSize: 12.5 }}>
                  {row.get(p) || '—'}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** [Check Skill Gap] result — same fields/shape as SkillGap on ProjectDetail
 * (backend/nlp/recommend.py:skill_gap), just laid out for chat width. */
function SkillGapBlock({ block }) {
  return (
    <div className="glass-panel w-full max-w-full p-3" style={{ borderRadius: 8 }}>
      <div className="flex items-center gap-3">
        <div className="h-1.5 flex-1 overflow-hidden rounded-full" style={{ background: 'var(--surface-container-high)' }}>
          <div className="h-full rounded-full" style={{ background: 'var(--primary)', width: `${block.readiness_percent}%` }} />
        </div>
        <span className="t-label-mono shrink-0 tabular-nums" style={{ color: 'var(--on-surface)', fontSize: 12 }}>
          {block.readiness_percent}% ready
        </span>
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div>
          <p className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>You have</p>
          <ul className="t-body-md mt-1 space-y-0.5" style={{ color: 'var(--on-surface-variant)', fontSize: 12.5 }}>
            {block.skills_you_have?.length ? block.skills_you_have.map((s) => <li key={s}>✓ {s}</li>) : <li style={{ color: 'var(--outline)' }}>None yet</li>}
          </ul>
        </div>
        <div>
          <p className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>Missing</p>
          <ul className="t-body-md mt-1 space-y-0.5" style={{ color: 'var(--on-surface-variant)', fontSize: 12.5 }}>
            {block.skills_to_learn?.length ? block.skills_to_learn.map((s) => <li key={s}>✗ {s}</li>) : <li style={{ color: 'var(--outline)' }}>None</li>}
          </ul>
        </div>
      </div>
    </div>
  )
}

/** [Project Timeline] result (backend/nlp/timeline.py:predict). */
function TimelineBlock({ block }) {
  return (
    <div className="glass-panel w-full max-w-full p-3" style={{ borderRadius: 8 }}>
      <BlockContextLabel projectId={block.project_id} title={block.title} />
      <p className="t-label-mono" style={{ color: 'var(--primary)', fontSize: 14 }}>
        {block.predicted_weeks} weeks
        <span className="t-body-md ml-2" style={{ color: 'var(--outline)', fontSize: 12 }}>
          ({block.team_size} {block.team_size === 1 ? 'person' : 'people'}, {block.experience_level})
        </span>
      </p>
      <ul className="t-body-md mt-2 space-y-1" style={{ color: 'var(--on-surface-variant)', fontSize: 12 }}>
        {block.factors?.map((f) => (
          <li key={f.factor}>· {f.note}</li>
        ))}
      </ul>
    </div>
  )
}

/** [Learning Path] result (backend/nlp/learning_path.py:sequenced_learning_path)
 * — already ordered learn-this-first by the backend, not this component;
 * `reason` (when present) is that ordering's own justification, shown as a
 * caption rather than re-derived here. */
function LearningPathBlock({ block }) {
  return (
    <div className="glass-panel w-full max-w-full space-y-3 p-3" style={{ borderRadius: 8 }}>
      {block.skills?.map(({ skill, resources, reason }, index) => (
        <div key={skill}>
          <div className="flex items-baseline gap-2">
            <span className="t-label-mono" style={{ color: 'var(--outline)', fontSize: 11 }}>{index + 1}.</span>
            <p className="t-label-mono" style={{ color: 'var(--on-surface)', fontSize: 12.5 }}>{skill}</p>
          </div>
          {reason && (
            <p className="t-body-md mt-0.5 pl-4" style={{ color: 'var(--outline)', fontSize: 11.5 }}>{reason}</p>
          )}
          <div className="mt-1.5 flex flex-wrap gap-1.5 pl-4">
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
    </div>
  )
}

/** [Milestones] result (backend/nlp/generator.py:milestones_for /
 * chat_tools.py:generate_milestones / generate_idea_milestones) — one
 * checkpoint per roadmap phase, so a milestone's week can never disagree
 * with the roadmap/timeline it was derived from. */
function MilestonesBlock({ block }) {
  return (
    <div className="glass-panel w-full max-w-full p-3" style={{ borderRadius: 8 }}>
      <BlockContextLabel projectId={block.project_id} title={block.title} />
      <p className="t-label-mono mb-2" style={{ color: 'var(--outline)', fontSize: 11 }}>
        {block.milestones?.length} checkpoints across {block.total_weeks} week{block.total_weeks === 1 ? '' : 's'}
      </p>
      <ol className="space-y-2">
        {block.milestones?.map((m) => (
          <li key={m.id} className="flex items-center gap-3">
            <span
              className="t-label-mono grid h-6 w-9 shrink-0 place-items-center rounded-full"
              style={{ background: 'var(--surface-container-highest)', color: 'var(--on-surface)', fontSize: 10 }}
            >
              {m.id}
            </span>
            <span className="t-body-md flex-1" style={{ color: 'var(--on-surface-variant)', fontSize: 12.5 }}>
              {m.title}
            </span>
            <span className="t-label-mono shrink-0 tabular-nums" style={{ color: 'var(--outline)', fontSize: 11.5 }}>
              wk {m.week}
            </span>
          </li>
        ))}
      </ol>
    </div>
  )
}

/** [Check my idea's uniqueness] result (backend/nlp/recommend.py:check_uniqueness,
 * via nlp/chat_tools.py:check_project_uniqueness). Same shape/fields as the
 * Idea Check page's own result panel, just laid out for chat width; the
 * similar projects reuse MiniProjectCard so Select Project works identically. */
function UniquenessBlock({ block, conversationId, selectedProjectId, onSelectProject }) {
  return (
    <div className="glass-panel w-full max-w-full p-3" style={{ borderRadius: 8 }}>
      <div className="flex items-baseline gap-2">
        <span className="t-label-mono" style={{ color: 'var(--primary)', fontSize: 16 }}>
          {block.originality_score}%
        </span>
        <span className="t-label-mono" style={{ color: 'var(--outline)', fontSize: 12 }}>
          {block.is_unique ? 'looks original' : 'originality'}
        </span>
      </div>

      {block.overlapping_concepts?.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {block.overlapping_concepts.map((c) => (
            <span key={c} className="gm-chip px-2 py-1">{c}</span>
          ))}
        </div>
      )}

      {block.suggestions?.length > 0 && (
        <ul className="t-body-md mt-2 space-y-1" style={{ color: 'var(--on-surface-variant)', fontSize: 12 }}>
          {block.suggestions.map((s) => (
            <li key={s}>· {s}</li>
          ))}
        </ul>
      )}

      {block.similar_projects?.length > 0 && (
        <div className="mt-3 flex w-full max-w-full gap-3 overflow-x-auto pb-1">
          {block.similar_projects.map((p) => (
            <MiniProjectCard
              key={p.project_id}
              project={{ ...p, match_score: p.similarity }}
              conversationId={conversationId}
              selectedProjectId={selectedProjectId}
              onSelectProject={onSelectProject}
            />
          ))}
        </div>
      )}
    </div>
  )
}

// Each action just sends a natural-language follow-up through the existing
// chat pipeline — the model resolves it against the idea by name via the
// '[Context — generated ideas shown above]' note (nlp/ai_assistant.py:
// _shown_ideas_note), the same pattern PROJECT_ACTIONS already uses for
// catalogue projects, so no dedicated endpoint exists for these.
const IDEA_ACTIONS = [
  { label: 'Build This', prompt: (idea) => `Let's build "${idea.name}".` },
  { label: 'Explore Idea', prompt: (idea) => `Tell me more about "${idea.name}".` },
  { label: 'Check Uniqueness', prompt: (idea) => `Is "${idea.name}" already available in your catalogue?` },
  { label: 'Compare', prompt: (idea) => `Compare "${idea.name}" with the closest existing project.` },
  { label: 'Improve Idea', prompt: (idea) => `Make "${idea.name}" more innovative.` },
  { label: 'Create Roadmap', prompt: (idea) => `Create a roadmap for "${idea.name}".` },
]

/** [Give me new/innovative project ideas] result (nlp/chat_tools.py:
 * generate_project_ideas), or a single refined idea from refine_project_idea
 * — both use this same block type/shape, so a refinement just renders as
 * one updated card rather than a second component. GeneratedIdeaCard itself
 * lives in components/GeneratedIdeaCard.jsx, shared with pages/Ideate.jsx
 * (the dedicated ideation workspace) so the "AI Generated Project Idea"
 * treatment is defined once. */
function GeneratedIdeasBlock({ block, onAction }) {
  return (
    <div className="w-full max-w-full space-y-3">
      {block.ideas?.map((idea) => (
        <GeneratedIdeaCard
          key={idea.id}
          idea={idea}
          actions={onAction ? IDEA_ACTIONS.map((action) => ({
            key: action.label,
            label: action.label,
            onClick: () => onAction(action.prompt(idea)),
          })) : undefined}
        />
      ))}
    </div>
  )
}

/** One project inside a [Give me your final recommendation] result —
 * real skill/timeline/uniqueness numbers from nlp/chat_tools.py:recommend_decision,
 * which itself only orchestrates check_skill_gap/predict_timeline/similar()'s
 * existing numbers, nothing computed here. */
function DecisionCandidate({ candidate, label, selectedProjectId, onSelectProject }) {
  const selected = candidate.project_id === selectedProjectId
  return (
    <div className="glass-panel p-4" style={{ borderRadius: 8 }}>
      <p className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>{label}</p>
      <div className="mt-1 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <Link to={`/project/${candidate.project_id}`} className="t-label-mono transition hover:opacity-75" style={{ color: 'var(--primary)', fontSize: 15 }}>
          {candidate.title}
        </Link>
        <span className="t-label-mono shrink-0" style={{ color: 'var(--primary)', fontSize: 13 }}>
          Overall fit {candidate.overall_fit}%
        </span>
      </div>

      {(candidate.strengths?.length > 0 || candidate.risks?.length > 0) && (
        <ul className="t-body-md mt-2 space-y-0.5" style={{ color: 'var(--on-surface-variant)', fontSize: 12.5 }}>
          {candidate.strengths?.map((s) => <li key={s}>✓ {s}</li>)}
          {candidate.risks?.map((r) => <li key={r}>⚠ {r}</li>)}
        </ul>
      )}

      {/* The four named evaluation factors (nlp/chat_tools.py:recommend_decision)
          — skill_fit/difficulty_fit are omitted rather than shown as 0% when
          their input (known_skills/experience_level) was never given, since
          that's a genuinely unavailable signal, not a real zero. */}
      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 t-label-mono" style={{ color: 'var(--outline)', fontSize: 11.5 }}>
        {candidate.skill_fit != null && <span>Skill fit: {candidate.skill_fit}%</span>}
        <span>Timeline fit: {candidate.timeline_fit}%</span>
        {candidate.difficulty_fit != null && <span>Difficulty fit: {candidate.difficulty_fit}%</span>}
        <span>Uniqueness: {candidate.uniqueness_percent}%</span>
      </div>
      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 t-label-mono" style={{ color: 'var(--outline)', fontSize: 11.5 }}>
        {candidate.skills_to_learn?.length > 0 && <span>Missing: {candidate.skills_to_learn.join(', ')}</span>}
        <span>Estimated: {candidate.estimated_weeks}wk · {candidate.team_size} {candidate.team_size === 1 ? 'person' : 'people'}</span>
        {candidate.target_weeks != null && <span>Target: {candidate.target_weeks}wk</span>}
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <Link to={`/project/${candidate.project_id}`} className="btn-secondary t-label-caps px-3 py-1.5" style={{ fontSize: 10.5 }}>
          View Project
        </Link>
        {onSelectProject && (
          <button
            type="button"
            onClick={() => onSelectProject(candidate)}
            disabled={selected}
            className="btn-primary t-label-caps px-3 py-1.5 disabled:opacity-60"
            style={{ fontSize: 10.5 }}
          >
            {selected ? 'Selected' : 'Select Project'}
          </button>
        )}
      </div>
    </div>
  )
}

/** [Give me your final recommendation] result (nlp/chat_tools.py:recommend_decision). */
function DecisionBlock({ block, selectedProjectId, onSelectProject }) {
  return (
    <div className="w-full max-w-full space-y-3">
      <DecisionCandidate
        candidate={block.recommended}
        label="Recommended Project"
        selectedProjectId={selectedProjectId}
        onSelectProject={onSelectProject}
      />
      {block.alternative && (
        <DecisionCandidate
          candidate={block.alternative}
          label="Alternative"
          selectedProjectId={selectedProjectId}
          onSelectProject={onSelectProject}
        />
      )}
    </div>
  )
}

/** [Can I build this? / How difficult is this?] result
 * (backend/nlp/feasibility.py:analyze_feasibility, via nlp/chat_tools.py:
 * analyze_project_feasibility / analyze_idea_feasibility) — every number here
 * is one of skill_gap/timeline.predict/difficulty_fit/domain-profile's own
 * real output, never invented; this component only lays it out. Same
 * ✓/⚠ strengths/risks vocabulary as DecisionCandidate above, so the two read
 * as one family rather than two different visual languages. */
function FeasibilityBlock({ block, onAction }) {
  const availableFactors = block.factors?.filter((f) => f.score != null) ?? []
  return (
    <div className="glass-panel w-full max-w-full p-3" style={{ borderRadius: 8 }}>
      <BlockContextLabel projectId={block.project_id} title={block.title} />
      <p className="t-label-mono" style={{ color: 'var(--primary)', fontSize: 16 }}>
        {block.feasibility_score}% feasible
        <span className="t-body-md ml-2" style={{ color: 'var(--outline)', fontSize: 12 }}>
          ({block.risk_level} risk)
        </span>
      </p>

      {availableFactors.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 t-label-mono" style={{ color: 'var(--outline)', fontSize: 11.5 }}>
          {availableFactors.map((f) => (
            <span key={f.factor}>{f.factor}: {f.score}%</span>
          ))}
        </div>
      )}

      {(block.strengths?.length > 0 || block.risks?.length > 0) && (
        <ul className="t-body-md mt-2 space-y-0.5" style={{ color: 'var(--on-surface-variant)', fontSize: 12.5 }}>
          {block.strengths?.map((s) => <li key={s}>✓ {s}</li>)}
          {block.risks?.map((r) => <li key={r}>⚠ {r}</li>)}
        </ul>
      )}

      {block.recommendations?.length > 0 && (
        <div className="mt-2">
          <p className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>Recommendations</p>
          <ul className="t-body-md mt-1 space-y-0.5" style={{ color: 'var(--on-surface-variant)', fontSize: 12 }}>
            {block.recommendations.map((r) => <li key={r}>· {r}</li>)}
          </ul>
        </div>
      )}

      {(block.infrastructure?.note || block.dataset?.note) && (
        <p className="t-label-mono mt-2" style={{ color: 'var(--outline)', fontSize: 11 }}>
          {[block.infrastructure?.note, block.dataset?.note].filter(Boolean).join(' · ')} (estimate)
        </p>
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        {block.project_id && (
          <Link to={`/project/${block.project_id}`} className="btn-secondary t-label-caps px-3 py-1.5" style={{ fontSize: 10.5 }}>
            View Details
          </Link>
        )}
        {onAction && (
          <button
            type="button"
            onClick={() => onAction('How can I reduce the risk for this project?')}
            className="btn-secondary t-label-caps px-3 py-1.5"
            style={{ fontSize: 10.5 }}
          >
            Reduce Risk
          </button>
        )}
      </div>
    </div>
  )
}

/** One MVP/CORE/ADVANCED/FUTURE tier inside a [What should this include? /
 * MVP?] result — reuses the same `gm-chip` pill style Search.jsx's
 * technology filters and UniquenessBlock's overlapping_concepts already use,
 * rather than a new chip treatment. */
function ScopeTierSection({ label, items }) {
  if (!items?.length) return null
  return (
    <div className="mt-2">
      <p className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>{label}</p>
      <div className="mt-1 flex flex-wrap gap-1.5">
        {items.map((item) => (
          <span key={item} className="gm-chip px-2 py-1">{item}</span>
        ))}
      </div>
    </div>
  )
}

/** [What should this include? / MVP? / "I only have N weeks"] result
 * (backend/nlp/feasibility.py:analyze_scope, via nlp/chat_tools.py:
 * analyze_scope) — every tier is one of the project's own real domain
 * modules or its own future_scope, never invented. `reduced_scope` is only
 * ever a suggestion computed from target_weeks vs the project's own
 * duration — Apply Scope Recommendation sends it through the same chat
 * pipeline as every other block action, it never mutates the project. */
function ScopeBlock({ block, onAction }) {
  return (
    <div className="glass-panel w-full max-w-full p-3" style={{ borderRadius: 8 }}>
      <BlockContextLabel projectId={block.project_id} title={block.title} />
      <ScopeTierSection label="MVP" items={block.mvp} />
      <ScopeTierSection label="Core" items={block.core} />
      <ScopeTierSection label="Advanced" items={block.advanced} />
      <ScopeTierSection label="Future" items={block.future} />

      {block.dependencies?.length > 0 && (
        <p className="t-body-md mt-2" style={{ color: 'var(--on-surface-variant)', fontSize: 12 }}>
          Depends on: {block.dependencies.join(', ')}
        </p>
      )}

      {block.technical_constraints?.length > 0 && (
        <ul className="t-body-md mt-2 space-y-0.5" style={{ color: 'var(--outline)', fontSize: 11.5 }}>
          {block.technical_constraints.map((c) => <li key={c}>· {c}</li>)}
        </ul>
      )}

      {block.reduced_scope && (
        <div className="mt-3 pt-2" style={{ borderTop: '1px solid var(--border-technical)' }}>
          <p className="t-label-caps" style={{ color: 'var(--primary)', fontSize: 10 }}>
            Suggested reduction for your timeline
          </p>
          <p className="t-body-md mt-1" style={{ color: 'var(--on-surface-variant)', fontSize: 12 }}>
            {block.reduced_scope.reason}
          </p>
          {block.reduced_scope.remove.length > 0 && (
            <p className="t-body-md mt-1" style={{ color: 'var(--on-surface-variant)', fontSize: 12 }}>
              <span style={{ color: 'var(--outline)' }}>Remove:</span> {block.reduced_scope.remove.join(', ')}
            </p>
          )}
          <p className="t-body-md mt-1" style={{ color: 'var(--on-surface-variant)', fontSize: 12 }}>
            <span style={{ color: 'var(--outline)' }}>Keep:</span> {block.reduced_scope.keep.join(', ')}
          </p>
        </div>
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        {block.reduced_scope && onAction && (
          <button
            type="button"
            onClick={() => onAction('Apply the suggested scope reduction — help me proceed with just the reduced scope.')}
            className="btn-primary t-label-caps px-3 py-1.5"
            style={{ fontSize: 10.5 }}
          >
            Apply Scope Recommendation
          </button>
        )}
        {onAction && (
          <button
            type="button"
            onClick={() => onAction(block.project_id ? 'Create a roadmap for this project.' : 'Create a roadmap for this idea.')}
            className="btn-secondary t-label-caps px-3 py-1.5"
            style={{ fontSize: 10.5 }}
          >
            Create Roadmap
          </button>
        )}
      </div>
    </div>
  )
}

/** One technology-stack layer inside a [How many people/what technologies do
 * I need?] result — same `gm-chip` treatment as ScopeTierSection, so the two
 * blocks read as one family. */
function ResourceTechSection({ label, items }) {
  if (!items?.length) return null
  return (
    <div className="mt-2">
      <p className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>{label}</p>
      <div className="mt-1 flex flex-wrap gap-1.5">
        {items.map((item) => (
          <span key={item} className="gm-chip px-2 py-1">{item}</span>
        ))}
      </div>
    </div>
  )
}

/** [How many people do I need? / What technologies do I need? / Can I build
 * this with free tools?] result (backend/nlp/feasibility.py:
 * estimate_resources, via nlp/chat_tools.py:estimate_project_resources) —
 * team size/roles from the project's own real domain modules, a technology
 * breakdown of its own real technologies, and a cost section that is always
 * a free-tier-first range, never an invented exact price (every cost line
 * below is server-computed text, not model output). */
function ResourceBlock({ block, onAction }) {
  const team = block.team ?? {}
  const tech = block.technology ?? {}
  const resources = block.resources ?? {}
  const cost = block.cost ?? {}
  const services = [...(resources.apis ?? []), ...(resources.external_services ?? [])]

  return (
    <div className="glass-panel w-full max-w-full p-3" style={{ borderRadius: 8 }}>
      <BlockContextLabel projectId={block.project_id} title={block.title} />
      <p className="t-label-mono" style={{ color: 'var(--primary)', fontSize: 14 }}>
        {team.recommended_size} {team.recommended_size === 1 ? 'person' : 'people'} recommended
        {team.given_size != null && (
          <span className="t-body-md ml-2" style={{ color: 'var(--outline)', fontSize: 12 }}>
            (you said {team.given_size})
          </span>
        )}
      </p>
      {team.roles?.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {team.roles.map((r) => (
            <span key={r.role} className="gm-chip px-2 py-1">{r.role} · {r.category}</span>
          ))}
        </div>
      )}
      {team.required_skills?.length > 0 && (
        <p className="t-body-md mt-1.5" style={{ color: 'var(--on-surface-variant)', fontSize: 12 }}>
          Skills needed: {team.required_skills.join(', ')}
        </p>
      )}

      <ResourceTechSection label="Frontend" items={tech.frontend} />
      <ResourceTechSection label="Backend" items={tech.backend} />
      <ResourceTechSection label="Database" items={tech.database} />
      <ResourceTechSection label="AI / ML" items={tech.ai_ml} />
      <ResourceTechSection label="Infrastructure" items={tech.infrastructure} />

      <div className="mt-3 space-y-1 pt-2" style={{ borderTop: '1px solid var(--border-technical)' }}>
        {resources.dataset?.note && (
          <p className="t-body-md" style={{ color: 'var(--on-surface-variant)', fontSize: 12 }}>
            <span style={{ color: 'var(--outline)' }}>Dataset:</span> {resources.dataset.note} (estimate)
          </p>
        )}
        {resources.compute?.note && (
          <p className="t-body-md" style={{ color: 'var(--on-surface-variant)', fontSize: 12 }}>
            <span style={{ color: 'var(--outline)' }}>Compute:</span> {resources.compute.note} (estimate)
          </p>
        )}
        {resources.storage?.note && (
          <p className="t-body-md" style={{ color: 'var(--on-surface-variant)', fontSize: 12 }}>
            <span style={{ color: 'var(--outline)' }}>Storage:</span> {resources.storage.note} (estimate)
          </p>
        )}
        {services.length > 0 && (
          <p className="t-body-md" style={{ color: 'var(--on-surface-variant)', fontSize: 12 }}>
            <span style={{ color: 'var(--outline)' }}>APIs/services:</span> {services.join(', ')}
          </p>
        )}
      </div>

      <div className="mt-3 pt-2" style={{ borderTop: '1px solid var(--border-technical)' }}>
        <p className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>
          Estimated cost{cost.is_estimate ? ' (estimate)' : ''}
        </p>
        <ul className="t-body-md mt-1 space-y-0.5" style={{ color: 'var(--on-surface-variant)', fontSize: 12 }}>
          {cost.development && <li>Development: {cost.development}</li>}
          {cost.infrastructure && <li>Infrastructure: {cost.infrastructure}</li>}
          {cost.api && <li>API: {cost.api}</li>}
          {cost.hosting && <li>Hosting: {cost.hosting}</li>}
        </ul>
        {cost.free_alternatives?.length > 0 && (
          <div className="mt-1.5">
            <p className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>Free / low-cost options</p>
            <ul className="t-body-md mt-1 space-y-0.5" style={{ color: 'var(--on-surface-variant)', fontSize: 12 }}>
              {cost.free_alternatives.map((a) => <li key={a}>· {a}</li>)}
            </ul>
          </div>
        )}
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        {onAction && (
          <button
            type="button"
            onClick={() => onAction(block.project_id ? 'Create a roadmap for this project.' : 'Create a roadmap for this idea.')}
            className="btn-secondary t-label-caps px-3 py-1.5"
            style={{ fontSize: 10.5 }}
          >
            Create Roadmap
          </button>
        )}
        {onAction && (
          <button
            type="button"
            onClick={() => onAction('Check my skill gap for this project.')}
            className="btn-secondary t-label-caps px-3 py-1.5"
            style={{ fontSize: 10.5 }}
          >
            Skill Gap
          </button>
        )}
      </div>
    </div>
  )
}

/** One fit/score stat inside the Decision Center — omitted entirely (not
 * shown as 0%) when its value is unavailable, same "unavailable is not a
 * real zero" rule every other block in this file already follows. Rendered
 * as a small bordered tile (not bare wrapped text) so the Project Fit row
 * reads as one grid of peer stats, clearly secondary to the single large
 * recommendation score above it. */
function ScoreStat({ label, value, suffix = '' }) {
  if (value == null) return null
  return (
    <div className="min-w-0 px-2.5 py-1.5" style={{ background: 'var(--surface-container-low)', border: '1px solid var(--border-technical)', borderRadius: 6 }}>
      <p className="t-label-caps truncate" style={{ color: 'var(--outline)', fontSize: 9 }}>{label}</p>
      <p className="t-label-mono truncate" style={{ color: 'var(--on-surface)', fontSize: 14 }}>{value}%{suffix}</p>
    </div>
  )
}

/** Recommendation-state → visual tone, built entirely from colors already
 * established elsewhere in this codebase: var(--primary) is the same
 * "emphasis" white every filled button/active chip already uses, and
 * #ffb4ab is the exact red every error/warning notice in this app already
 * uses (Feedback.jsx's ErrorNotice, every form's inline error text — see
 * ComposerError above). No new colors. `label` is one of the three fixed
 * strings decision_center.py's _RECOMMENDATION_BANDS produces. */
function recommendationTone(label) {
  if (label === 'Recommended') {
    return { fg: 'var(--primary)', border: 'var(--primary)', dot: 'var(--primary)' }
  }
  if (label === 'High risk — reconsider or reduce scope') {
    return { fg: '#ffb4ab', border: 'rgba(255,180,171,0.4)', dot: '#ffb4ab' }
  }
  return { fg: 'var(--on-surface)', border: 'var(--border-technical)', dot: 'var(--outline)' }
}

/** Shown only while the read-only GET assembling the Decision Center is in
 * flight — distinct from "nothing selected" (nothing renders at all) and
 * "the fetch failed" (falls back to the plain action chips), so a slow
 * response reads as "working on it" rather than a blank gap or a stuck
 * layout. Same spinner technique as Feedback.jsx's Spinner, scaled down to
 * fit inline in a card instead of a full-page state. */
function DecisionCenterLoading() {
  return (
    <div className="glass-panel w-full max-w-full p-4" style={{ borderRadius: 10 }}>
      <div className="flex items-center gap-2.5">
        <span
          className="h-3.5 w-3.5 shrink-0 animate-spin rounded-full border-2"
          style={{ borderColor: 'var(--border-technical)', borderTopColor: 'var(--primary)' }}
        />
        <p className="t-label-mono" style={{ color: 'var(--on-surface-variant)', fontSize: 12 }}>
          Preparing your decision summary…
        </p>
      </div>
    </div>
  )
}

/** The unified Project Decision / Action Center — combines outputs already
 * computed by the existing analyzers (feasibility, scope, resources, and,
 * for a catalogue project, the Decision Engine) into one view for whichever
 * project/idea is currently active (backend/nlp/decision_center.py). No LLM
 * call: every number here already exists, this component only lays it out,
 * ordered RECOMMENDATION → WHY → PROJECT FIT → RISKS → SCOPE → RESOURCES →
 * NEXT ACTION so it reads as the final stage of Discover → Evaluate →
 * Feasibility → Scope → Resources → Decide, not a flat dump of numbers.
 * Every action sends a canned prompt through the existing chat pipeline
 * (onAction === send), same mechanism PROJECT_ACTIONS/IDEA_BUILD_ACTIONS
 * already use — no new endpoints behind any of them except the read itself. */
function DecisionCenterBlock({ data, onAction }) {
  if (!data || data.error) return null
  const isIdea = data.kind === 'idea'
  const rec = data.overall_recommendation ?? {}
  const feasibility = data.feasibility ?? {}
  const time = data.timeline ?? {}
  const originality = data.originality ?? {}
  const scope = data.scope ?? {}
  const resources = data.resources ?? {}
  const scopeTierCount = (scope.mvp?.length ?? 0) + (scope.core?.length ?? 0) + (scope.advanced?.length ?? 0)
  const tone = recommendationTone(rec.label)
  const roadmapPrompt = isIdea ? `Create a roadmap for "${data.name}".` : 'Create a roadmap for this project.'
  const scopePrompt = isIdea ? `What should the MVP be for "${data.name}"?` : 'What should the MVP be for this project?'
  const resourcesPrompt = isIdea
    ? `What resources do I need for "${data.name}"?`
    : 'What resources do I need for this project?'
  const comparePrompt = isIdea
    ? `Compare "${data.name}" with the closest existing project.`
    : 'Compare this project with similar alternatives.'
  const skillGapPrompt = 'Check my skill gap for this project.'

  // WHY — the same numbers shown in the Project Fit row below, read back as
  // one sentence so the score at the top always comes with an immediate
  // reason attached, instead of making the reader cross-reference stats
  // further down the card themselves.
  const whyParts = []
  if (data.skill_fit != null) whyParts.push(`${data.skill_fit}% skill fit`)
  if (feasibility.risk_level) whyParts.push(`${feasibility.risk_level.toLowerCase()} risk`)
  if (originality.score != null) whyParts.push(`${originality.score}% ${isIdea ? 'originality' : 'uniqueness'}`)
  const whyLine = whyParts.length > 0 ? `Based on ${whyParts.join(', ')}.` : null

  // The one existing action most worth surfacing next to the Next Step
  // text — derived from the same known_skills_provided/reduced_scope
  // signals decision_center.py's own recommended_next_step already used to
  // write that sentence (never a second copy of that reasoning). Left
  // unset (falls through to the always-visible Generate Roadmap primary
  // button) rather than ever showing a second, disconnected suggestion.
  let nextStepAction = null
  if (data.recommended_next_step) {
    if (!isIdea && !data.known_skills_provided) {
      nextStepAction = { label: 'Check Skill Gap', prompt: skillGapPrompt }
    } else if (scope.reduced_scope) {
      nextStepAction = { label: 'View Scope', prompt: scopePrompt }
    }
  }

  return (
    <div className="glass-panel w-full max-w-full p-4" style={{ borderRadius: 10, border: `1px solid ${tone.border}` }}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="gm-chip px-2 py-1" style={{ fontSize: 9.5 }}>
          {isIdea ? 'AI-Generated Idea' : 'Catalogue Project'}
        </span>
        <span className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 9 }}>Decision Center</span>
      </div>

      {/* RECOMMENDATION — the single strongest visual element on this card;
          everything below only explains or acts on this one number. */}
      <div className="mt-3 flex flex-wrap items-end justify-between gap-4 pb-3" style={{ borderBottom: '1px solid var(--border-technical)' }}>
        <div className="min-w-0">
          <p className="t-label-mono truncate" style={{ color: 'var(--primary)', fontSize: 17 }}>{data.name}</p>
          <p className="t-label-mono" style={{ color: 'var(--outline)', fontSize: 11 }}>
            {[data.difficulty, data.domain, data.duration_weeks ? `${data.duration_weeks} weeks` : null]
              .filter(Boolean)
              .join(' · ')}
          </p>
        </div>
        {rec.score != null && (
          <div className="text-right">
            {rec.label && (
              <div className="flex items-center justify-end gap-1.5">
                <span aria-hidden="true" style={{ width: 6, height: 6, borderRadius: '50%', background: tone.dot, display: 'inline-block' }} />
                <p className="t-label-caps" style={{ color: tone.fg, fontSize: 11 }}>{rec.label}</p>
              </div>
            )}
            <p className="t-label-mono" style={{ color: tone.fg, fontSize: 32, lineHeight: 1.15 }}>{rec.score}%</p>
          </div>
        )}
      </div>

      {/* WHY */}
      {whyLine && (
        <p className="t-body-md mt-2.5" style={{ color: 'var(--on-surface-variant)', fontSize: 12.5 }}>
          {whyLine}
        </p>
      )}

      {/* PROJECT FIT */}
      {(data.skill_fit != null || time.fit_score != null || data.difficulty_fit != null || feasibility.score != null || originality.score != null) && (
        <div className="mt-3">
          <p className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>Project Fit</p>
          <div className="mt-1.5 grid grid-cols-2 gap-1.5 sm:grid-cols-3 lg:grid-cols-5">
            <ScoreStat label="Skill Fit" value={data.skill_fit} />
            <ScoreStat label="Timeline Fit" value={time.fit_score} />
            <ScoreStat label="Difficulty Fit" value={data.difficulty_fit} />
            <ScoreStat label="Feasibility" value={feasibility.score} suffix={feasibility.risk_level ? ` (${feasibility.risk_level})` : ''} />
            <ScoreStat label={isIdea ? 'Originality' : 'Uniqueness'} value={originality.score} />
          </div>
          {time.estimated_weeks != null && (
            <p className="t-body-md mt-1.5" style={{ color: 'var(--on-surface-variant)', fontSize: 12 }}>
              Estimated {time.estimated_weeks}wk build
            </p>
          )}
        </div>
      )}

      {/* RISKS (and STRENGTHS) — grouped into their own labeled sections
          rather than one merged bullet list, so a risk never reads like a
          strength at a glance. */}
      {(data.strengths?.length > 0 || data.risks?.length > 0) && (
        <div className="mt-3 grid gap-x-4 gap-y-2 sm:grid-cols-2">
          {data.strengths?.length > 0 && (
            <div>
              <p className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>Strengths</p>
              <ul className="t-body-md mt-1 space-y-0.5" style={{ color: 'var(--on-surface-variant)', fontSize: 12.5 }}>
                {data.strengths.slice(0, 4).map((s) => <li key={s}>✓ {s}</li>)}
              </ul>
            </div>
          )}
          {data.risks?.length > 0 && (
            <div>
              <p className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>Risks</p>
              <ul className="t-body-md mt-1 space-y-0.5" style={{ color: 'var(--on-surface-variant)', fontSize: 12.5 }}>
                {data.risks.slice(0, 4).map((r) => <li key={r}>⚠ {r}</li>)}
              </ul>
            </div>
          )}
        </div>
      )}

      {data.skills_to_learn?.length > 0 && (
        <p className="t-body-md mt-2" style={{ color: 'var(--on-surface-variant)', fontSize: 12 }}>
          <span style={{ color: 'var(--outline)' }}>Skill gaps:</span> {data.skills_to_learn.join(', ')}
        </p>
      )}

      {/* SCOPE / RESOURCES — one-line summaries only; View Scope/View
          Resources below open the full breakdown from their own dedicated
          blocks, this never repeats that detail. */}
      {(scopeTierCount > 0 || resources.team_recommended_size != null) && (
        <div className="mt-3 grid gap-x-4 gap-y-2 pt-3 sm:grid-cols-2" style={{ borderTop: '1px solid var(--border-technical)' }}>
          {scopeTierCount > 0 && (
            <div>
              <p className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>Scope</p>
              <p className="t-body-md mt-1" style={{ color: 'var(--on-surface-variant)', fontSize: 12 }}>
                {scope.mvp?.length ?? 0} MVP · {scope.core?.length ?? 0} core · {scope.advanced?.length ?? 0} advanced
                {scope.reduced_scope ? ' · reduction suggested for your timeline' : ''}
              </p>
            </div>
          )}
          {resources.team_recommended_size != null && (
            <div>
              <p className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>Resources</p>
              <p className="t-body-md mt-1" style={{ color: 'var(--on-surface-variant)', fontSize: 12 }}>
                {resources.team_recommended_size} {resources.team_recommended_size === 1 ? 'person' : 'people'} recommended
                {resources.cost_is_estimate ? ' · free-tier friendly (estimate)' : ''}
              </p>
            </div>
          )}
        </div>
      )}

      {/* NEXT ACTION — the most prominent callout on the card after the
          recommendation itself, paired with whichever single existing
          action is most relevant right now (never duplicated below). */}
      {data.recommended_next_step && (
        <div className="mt-3 p-3" style={{ background: 'rgba(255,255,255,0.06)', border: '1px solid var(--primary)', borderRadius: 8 }}>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-0">
              <p className="t-label-caps" style={{ color: 'var(--primary)', fontSize: 10 }}>Next Step</p>
              <p className="t-body-md mt-1" style={{ color: 'var(--on-surface)', fontSize: 13 }}>
                {data.recommended_next_step}
              </p>
            </div>
            {nextStepAction && (
              <button
                type="button"
                onClick={() => onAction(nextStepAction.prompt)}
                className="btn-primary t-label-caps shrink-0 px-3 py-1.5"
                style={{ fontSize: 10.5 }}
              >
                {nextStepAction.label}
              </button>
            )}
          </div>
        </div>
      )}

      {/* ACTIONS — Start This Project and Generate Roadmap are the primary
          pair; everything else is secondary. Whichever of Check Skill
          Gap/View Scope is already shown as the Next Step's own button
          above is not repeated in the secondary row. */}
      <div className="mt-3 flex flex-wrap gap-2">
        {!isIdea && data.project_id ? (
          <Link to={`/project/${data.project_id}`} className="btn-primary t-label-caps px-3 py-1.5" style={{ fontSize: 10.5 }}>
            Start This Project
          </Link>
        ) : (
          <button
            type="button"
            onClick={() => onAction(`Let's build "${data.name}".`)}
            className="btn-primary t-label-caps px-3 py-1.5"
            style={{ fontSize: 10.5 }}
          >
            Start This Project
          </button>
        )}
        <button type="button" onClick={() => onAction(roadmapPrompt)} className="btn-primary t-label-caps px-3 py-1.5" style={{ fontSize: 10.5 }}>
          Generate Roadmap
        </button>
      </div>
      <div className="mt-2 flex flex-wrap gap-2">
        {!isIdea && nextStepAction?.label !== 'Check Skill Gap' && (
          <button
            type="button"
            onClick={() => onAction(skillGapPrompt)}
            className="btn-secondary t-label-caps px-3 py-1.5"
            style={{ fontSize: 10.5 }}
          >
            Check Skill Gap
          </button>
        )}
        {nextStepAction?.label !== 'View Scope' && (
          <button type="button" onClick={() => onAction(scopePrompt)} className="btn-secondary t-label-caps px-3 py-1.5" style={{ fontSize: 10.5 }}>
            View Scope
          </button>
        )}
        <button type="button" onClick={() => onAction(resourcesPrompt)} className="btn-secondary t-label-caps px-3 py-1.5" style={{ fontSize: 10.5 }}>
          View Resources
        </button>
        <button type="button" onClick={() => onAction(comparePrompt)} className="btn-secondary t-label-caps px-3 py-1.5" style={{ fontSize: 10.5 }}>
          Compare
        </button>
        <Link to="/dashboard" className="btn-secondary t-label-caps px-3 py-1.5" style={{ fontSize: 10.5 }}>
          Change Project
        </Link>
      </div>
    </div>
  )
}

/** Persistent "you're working on X" strip — the workspace context indicator.
 * Shown once a project is selected (via the select_project tool or the
 * [Select Project] button); links to the existing Project Detail page,
 * which is where the actual workspace features (roadmap, skill gap, team
 * builder, ...) already live — this never rebuilds any of them. */
function ActiveProjectBanner({ project }) {
  if (!project) return null
  return (
    <div className="mx-auto flex w-full max-w-3xl items-center gap-3 px-1 pb-3">
      <span className="t-label-caps shrink-0" style={{ color: 'var(--outline)', fontSize: 10 }}>
        Working on
      </span>
      <Link
        to={`/project/${project.project_id}`}
        className="t-label-mono truncate transition hover:opacity-75"
        style={{ color: 'var(--primary)', fontSize: 12.5 }}
      >
        {project.title}
      </Link>
      <span style={{ color: 'var(--border-technical)' }}>·</span>
      <span className="t-label-mono truncate" style={{ color: 'var(--outline)', fontSize: 12 }}>
        {project.difficulty} · {project.domain}
      </span>
    </div>
  )
}

/** Persistent "you're working on X" strip for a GENERATED idea — the
 * idea-context mirror of ActiveProjectBanner above, shown once the student
 * selects a generated idea (via the select_idea tool or the [Build This]
 * action). No project route to link to — a generated idea has no
 * project_id — so this renders as plain text instead of a Link. */
function ActiveIdeaBanner({ idea }) {
  if (!idea) return null
  const detail = [idea.difficulty, idea.domain].filter(Boolean).join(' · ')
  return (
    <div className="mx-auto flex w-full max-w-3xl items-center gap-3 px-1 pb-3">
      <span className="t-label-caps shrink-0" style={{ color: 'var(--outline)', fontSize: 10 }}>
        Building
      </span>
      <span className="t-label-mono truncate" style={{ color: 'var(--primary)', fontSize: 12.5 }}>
        {idea.name}
      </span>
      <span style={{ color: 'var(--border-technical)' }}>·</span>
      <span className="t-label-mono truncate" style={{ color: 'var(--outline)', fontSize: 12 }}>
        AI-generated idea{detail ? ` · ${detail}` : ''}
      </span>
    </div>
  )
}

/**
 * "What this answer used" - rendered from the server's own `grounding` block
 * (backend/nlp/personal_tools.py), which lists the saved ProjectMind data the
 * assistant actually retrieved this turn (profile, skill gap, roadmap progress,
 * team data) and a few fixed follow-up questions. It is built from tool calls,
 * never from the model's text, so it cannot claim a source that was not read.
 */
function GroundingBlock({ block, onAction }) {
  if (!block?.sources?.length) return null
  return (
    <div className="w-full max-w-[85%]" aria-label="Data used for this answer">
      <p className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>Used from ProjectMind</p>
      <ul className="mt-1 flex flex-wrap gap-1.5">
        {block.sources.map((s) => (
          <li key={`${s.kind}-${s.label}`} className="gm-chip px-2 py-0.5" style={{ fontSize: 11 }}>
            {s.label}
          </li>
        ))}
      </ul>
      {onAction && block.follow_ups?.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5" aria-label="Suggested follow-up questions">
          {block.follow_ups.map((text) => (
            <button
              key={text}
              type="button"
              onClick={() => onAction(text)}
              className="btn-secondary t-label-caps px-3 py-1.5"
              style={{ fontSize: 10.5 }}
            >
              {text}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function Bubble({ role, content, blocks, conversationId, selectedProjectId, onSelectProject, onAction }) {
  const isUser = role === 'user'
  const recommended = projectsFromBlocks(blocks)
  const comparison = blockOfType(blocks, 'comparison')
  const skillGap = blockOfType(blocks, 'skill_gap')
  const timelineResult = blockOfType(blocks, 'timeline')
  const learningPath = blockOfType(blocks, 'learning_path')
  const milestones = blockOfType(blocks, 'milestones')
  const uniqueness = blockOfType(blocks, 'uniqueness')
  const decision = blockOfType(blocks, 'decision')
  const feasibilityResult = blockOfType(blocks, 'feasibility')
  const scopeResult = blockOfType(blocks, 'scope')
  const resourcesResult = blockOfType(blocks, 'resources')
  const generatedIdeas = blockOfType(blocks, 'generated_project_ideas')
  const grounding = blockOfType(blocks, 'grounding')

  return (
    <div className={`flex flex-col gap-2 ${isUser ? 'items-end' : 'items-start'}`}>
      {content && (
        <div className={`group flex max-w-[85%] items-end gap-1 ${isUser ? 'flex-row-reverse' : ''}`}>
          <div
            className="px-3.5 py-2.5 text-sm leading-relaxed"
            style={
              isUser
                ? { whiteSpace: 'pre-wrap', background: 'var(--primary)', color: 'var(--on-primary)', borderRadius: 8 }
                : { background: 'var(--surface-container-low)', color: 'var(--on-surface-variant)', border: '1px solid var(--border-technical)', borderRadius: 8 }
            }
          >
            {isUser ? content : <MarkdownLite content={content} />}
          </div>
          {!isUser && <CopyButton text={content} />}
        </div>
      )}
      {!isUser && grounding && <GroundingBlock block={grounding} onAction={onAction} />}
      {recommended.length > 0 && (
        <div className="flex w-full max-w-full gap-3 overflow-x-auto pb-1">
          {recommended.map((p) => (
            <MiniProjectCard
              key={p.project_id}
              project={p}
              conversationId={conversationId}
              selectedProjectId={selectedProjectId}
              onSelectProject={onSelectProject}
            />
          ))}
        </div>
      )}
      {comparison && <ComparisonBlock block={comparison} />}
      {skillGap && <SkillGapBlock block={skillGap} />}
      {timelineResult && <TimelineBlock block={timelineResult} />}
      {learningPath && <LearningPathBlock block={learningPath} />}
      {milestones && <MilestonesBlock block={milestones} />}
      {uniqueness && (
        <UniquenessBlock
          block={uniqueness}
          conversationId={conversationId}
          selectedProjectId={selectedProjectId}
          onSelectProject={onSelectProject}
        />
      )}
      {decision && (
        <DecisionBlock block={decision} selectedProjectId={selectedProjectId} onSelectProject={onSelectProject} />
      )}
      {feasibilityResult && <FeasibilityBlock block={feasibilityResult} onAction={onAction} />}
      {scopeResult && <ScopeBlock block={scopeResult} onAction={onAction} />}
      {resourcesResult && <ResourceBlock block={resourcesResult} onAction={onAction} />}
      {generatedIdeas && <GeneratedIdeasBlock block={generatedIdeas} onAction={onAction} />}
    </div>
  )
}

/** Extremely subtle technical texture behind the empty state — the same
 * "grounded system" language as the landing page (faint labels, tiny
 * nodes), at low enough opacity to read as ambient decoration rather than
 * content. Purely decorative: no data, no interaction. */
function EmptyStateBackdrop() {
  return (
    <div className="pointer-events-none absolute inset-0 z-0 hidden lg:block" aria-hidden="true">
      {BACKDROP_LABELS.map((label) => (
        <span key={label.text} className="backdrop-label" style={label.style}>
          {label.text}
        </span>
      ))}
      {BACKDROP_NODES.map((pos, i) => (
        <span key={i} className="backdrop-node" style={pos} />
      ))}
    </div>
  )
}

/** The ProjectMind AI message form — extracted so the empty state can place
 * it as part of the hero flow (see the Dashboard render below) while the
 * active-thread view keeps it pinned to the viewport bottom, without
 * duplicating this markup in both places. Same exact styling/behavior
 * either way — only where it sits in the layout changes. */
function Composer({ input, setInput, send, busy, voiceSupported, listening, start, stop, composerRef }) {
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        send()
      }}
      className="glass-panel composer-shell flex flex-col p-3"
      style={{ borderRadius: 12 }}
    >
      <span className="t-label-caps mb-1.5 px-1" style={{ color: 'var(--outline)', fontSize: 9.5 }}>
        ProjectMind AI
      </span>
      <textarea
        ref={composerRef}
        value={input}
        onChange={(event) => setInput(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault()
            send()
          }
        }}
        placeholder="Describe the project you want to build, or ask a question…"
        rows={1}
        aria-label="Message ProjectMind"
        className="w-full resize-none border-none bg-transparent px-1 outline-none"
        style={{ color: 'var(--primary)', fontFamily: 'Geist, sans-serif', fontSize: 16, minHeight: 56, maxHeight: 200 }}
      />
      <div className="mt-2 flex items-center justify-between px-1 pb-1">
        <Link
          to="/resume-match"
          title="Match projects to your résumé instead"
          className="grid h-9 w-9 place-items-center transition hover:bg-white/10"
          style={{ color: 'var(--outline)', border: '1px solid var(--border-technical)', borderRadius: 6 }}
        >
          <span className="material-symbols-outlined" style={{ fontSize: 19 }}>
            attach_file
          </span>
        </Link>
        <div className="flex items-center gap-2">
          {voiceSupported && (
            <button
              type="button"
              onClick={() => (listening ? stop() : start(setInput))}
              aria-label={listening ? 'Stop voice search' : 'Search by voice'}
              aria-pressed={listening}
              className="grid h-9 w-9 place-items-center transition hover:bg-white/10"
              style={{ color: listening ? 'var(--primary)' : 'var(--outline)', border: '1px solid var(--border-technical)', borderRadius: 6 }}
            >
              <span className="material-symbols-outlined" style={{ fontSize: 19 }}>
                mic
              </span>
            </button>
          )}
          <button
            type="submit"
            disabled={busy || !input.trim()}
            aria-label="Send"
            className="ml-1 grid h-9 w-9 place-items-center transition hover:opacity-85 active:scale-95 disabled:opacity-40"
            style={{ background: 'var(--primary)', color: 'var(--on-primary)', borderRadius: 6 }}
          >
            <span className="material-symbols-outlined" style={{ fontSize: 20 }}>
              arrow_upward
            </span>
          </button>
        </div>
      </div>
    </form>
  )
}

/** Error + retry, shown wherever the Composer is — both the empty-state
 * hero flow and the pinned active-thread footer can surface a failed send.
 *
 * `failedMessage` is shown here, not just held for Retry to resend — the
 * chat bubble it would have become was rolled back (see performSend, so
 * Retry doesn't duplicate it once resent), and a bare "something went
 * wrong" banner with no trace of what was typed reads exactly like the
 * message vanished. Showing the text here, next to Retry, makes clear it's
 * still right here, not lost. */
function ComposerError({ error, failedMessage, onRetry }) {
  if (!error) return null
  return (
    <div className="mb-2 flex flex-col items-center gap-1 px-4">
      <div className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1">
        <p className="t-label-mono" style={{ color: '#ffb4ab', fontSize: 11 }}>
          {error}
        </p>
        {failedMessage && (
          <button
            type="button"
            onClick={onRetry}
            className="t-label-mono transition hover:opacity-70"
            style={{ color: 'var(--primary)', fontSize: 11, textDecoration: 'underline' }}
          >
            Retry
          </button>
        )}
      </div>
      {failedMessage && (
        <p className="t-label-mono w-full max-w-md truncate text-center" style={{ color: 'var(--outline)', fontSize: 10.5 }}>
          Not sent yet: "{failedMessage}"
        </p>
      )}
    </div>
  )
}

/**
 * Dashboard — the app's one home, ChatGPT-shaped: a single box that both
 * chats and searches at once.
 *
 * When the AI assistant is configured, one call does the whole turn: the
 * assistant (nlp/ai_assistant.py:general_reply) is RAG-grounded via tool
 * calling, so it searches ProjectMind's own catalogue itself instead of the
 * frontend running its own parallel `/api/search` — that used to mean two
 * independent answers to the same message that could disagree, and a plain
 * keyword `/api/search` call on a purely conversational follow-up like "the
 * second one" returned noise. The assistant's reply carries `blocks` —
 * structured project cards, not parsed out of its Markdown — which get
 * stored on the conversation server-side, so they survive a refresh exactly
 * like the text does. Without an API key, this degrades to a plain
 * `/api/search` call with no memory across turns — the same shape search had
 * before an assistant existed, so the app stays fully usable either way.
 *
 * Sign-in required: every message goes through the gate below (see
 * AuthGateModal) before it actually sends — a signed-out visitor typing
 * here gets the same modal the landing page's hero box shows, and the
 * message they were sending is preserved and fires the moment they're in.
 */
export default function Dashboard() {
  const { user, loading: authLoading } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()
  const conversationId = searchParams.get('c')
  // Mirrors `conversationId` for performSend's auto-retry timer below: that
  // timer's callback is a closure fixed to the render it was scheduled in,
  // so a plain read of `conversationId` there would still see "no
  // conversation yet" even after the first (failed) attempt already created
  // one — a ref is mutable and always reflects the latest render, exactly
  // what a callback firing after a delay needs.
  const conversationIdRef = useRef(conversationId)
  conversationIdRef.current = conversationId

  const [available, setAvailable] = useState(null)
  const [messages, setMessages] = useState([])
  const [loadingThread, setLoadingThread] = useState(false)
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [failedMessage, setFailedMessage] = useState(null)
  const [selectedProjectId, setSelectedProjectId] = useState(null)
  const [selectedProject, setSelectedProject] = useState(null)
  // The GENERATED-idea counterpart of selectedProjectId/selectedProject —
  // mutually exclusive with them server-side (see routes/assistant.py), so
  // both are always assigned together from the same server response rather
  // than derived from each other. Unlike a catalogue project, the idea's
  // full fields already come back inline (no project_id to look up), so
  // there's no equivalent of the selectedProject fetch-by-id effect below.
  const [selectedIdea, setSelectedIdea] = useState(null)
  // The unified Decision/Action Center for whichever of the two above is
  // currently active (see DecisionCenterBlock) — fetched fresh whenever the
  // selection changes, via the read-only GET that assembles it server-side
  // (backend/nlp/decision_center.py). `decisionCenter` stays null whenever
  // nothing is selected yet, the fetch is still in flight, or it failed —
  // `decisionCenterLoading`/`decisionCenterError` disambiguate those so the
  // render below can show a loading state, then either the real block or
  // (on failure, same as before) the plain action-chip fallback, instead of
  // one flat "null means hidden" state that reads as a blank gap while the
  // request is still in flight.
  const [decisionCenter, setDecisionCenter] = useState(null)
  const [decisionCenterLoading, setDecisionCenterLoading] = useState(false)
  const [decisionCenterError, setDecisionCenterError] = useState(false)
  const [authGateOpen, setAuthGateOpen] = useState(false)
  const [gatedText, setGatedText] = useState('')
  const scrollAreaRef = useRef(null)
  const composerRef = useRef(null)
  // Which conversation's messages are currently reflected in `messages` —
  // distinct from `conversationId` (the URL) so this component can tell "we
  // already have this one loaded" (just-sent turns, already up to date) from
  // "the URL points somewhere our state hasn't caught up to yet" (a fresh
  // load, a refresh, or switching to a different saved conversation).
  const loadedConversationRef = useRef(null)
  const loadedProjectRef = useRef(null)
  const { supported: voiceSupported, listening, start, stop } = useVoiceSearch()
  // A "busy right now" failure (routes/assistant.py's LLM_RATE_LIMITED —
  // every configured Groq key momentarily out of quota) usually clears
  // within a few seconds, unlike every other chat failure here. One silent,
  // bounded auto-retry per message beats making the student notice and
  // click Retry themselves for something that resolves on its own — see
  // performSend below. autoRetriedRef caps it at exactly one attempt per
  // message so a *persistent* outage still falls through to the normal
  // error + manual Retry state instead of retrying forever.
  const autoRetriedRef = useRef(false)
  const retryTimerRef = useRef(null)
  useEffect(() => () => window.clearTimeout(retryTimerRef.current), [])

  useEffect(() => {
    api
      .health()
      .then((data) => setAvailable(Boolean(data?.ai_assistant?.enabled)))
      .catch(() => setAvailable(false))
  }, [])

  // Picks up a query the landing page's gate carried across the sign-in
  // redirect (see Search.jsx submitFromLanding + utils/pendingQuery). Waits
  // on both auth and the health check so `send()` doesn't re-open the gate
  // on a `user` that just hasn't finished loading yet, and so the AI-reply
  // branch is available for this very first message instead of silently
  // degrading to search-only.
  //
  // Only fires for a fresh landing hand-off (no `c` in the URL, and never
  // had one this mount) — opening one specific saved conversation was never
  // what this query was for. `hadConversationOnLoadRef` (captured once,
  // before any effect can mutate the URL) is what makes this survive the
  // signed-out "?c= gets stripped" bounce below: without it, that bounce
  // changes `conversationId` from set to empty, re-running this effect and
  // making a stale query look like a fresh landing hand-off again. Without
  // the guard at all, a query abandoned on the landing page (gate opened,
  // then navigated away some other way instead of closing the modal or
  // signing in) sits in sessionStorage and "resurrects" the next time
  // Dashboard mounts for *any* reason, wrongly popping the sign-in gate over
  // a conversation the user only meant to view.
  const hadConversationOnLoadRef = useRef(Boolean(searchParams.get('c')))
  useEffect(() => {
    if (authLoading || available === null) return
    if (conversationId || hadConversationOnLoadRef.current) {
      clearPendingQuery()
      return
    }
    const pending = takePendingQuery()
    if (pending) send(pending)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authLoading, available, conversationId])

  useEffect(() => {
    if (!conversationId) {
      setMessages([])
      setSelectedProjectId(null)
      setSelectedIdea(null)
      loadedConversationRef.current = null
      return
    }
    if (authLoading) return
    if (!user) {
      // A conversation thread is authenticated-only workspace state now
      // that sending requires an account (see the gate in send() below) —
      // a signed-out visitor hitting a stale `?c=` link (bookmark, direct
      // URL, browser history) should land on a clean composer, not a
      // fetched thread that makes the app look like it has an active
      // session. Same `user` check every other protected surface uses.
      setMessages([])
      setSelectedProjectId(null)
      setSelectedIdea(null)
      loadedConversationRef.current = null
      const next = new URLSearchParams(searchParams)
      next.delete('c')
      setSearchParams(next, { replace: true })
      return
    }
    if (loadedConversationRef.current === conversationId) {
      // `send()` just created this conversation and already has its first
      // turn (including the recommendation blocks) in local state — refetching
      // here would replace it with whatever the server had at that instant,
      // which used to be a race that could win *before* the write landed and
      // silently drop the cards that had just been shown.
      return
    }
    let cancelled = false
    setLoadingThread(true)
    api
      .getConversation(conversationId)
      .then(({ data }) => {
        if (cancelled) return
        setMessages(data.messages.map((m) => ({ role: m.role, content: m.content, blocks: m.blocks })))
        setSelectedProjectId(data.selected_project_id ?? null)
        setSelectedIdea(data.selected_idea ?? null)
        loadedConversationRef.current = conversationId
      })
      .catch(() => {
        if (!cancelled) setError('Could not load that conversation.')
      })
      .finally(() => {
        if (!cancelled) setLoadingThread(false)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId, authLoading, user])

  useEffect(() => {
    // decisionCenter is included because it loads asynchronously, after
    // `messages` has already settled: without it, this effect only ever
    // scrolls to where the bottom was *before* the Decision Center card
    // finished expanding, silently leaving its lower actions (View Scope,
    // Compare, Change Project) below the fold with no scroll cue.
    //
    // Scrolls the container directly to its own scrollHeight, not
    // `scrollIntoView` on a marker element — measured live: with a tall
    // Decision Center card, `scrollIntoView({block: 'nearest'})` stopped
    // ~20px short of the true bottom (just enough for the last action row —
    // View Scope/Compare/Change Project — to sit under the pinned
    // ActiveProjectBanner), and `block: 'end'` was worse, landing even
    // further short — `scrollIntoView`'s alignment re-targets against a
    // marker element whose own position keeps shifting as this same effect
    // re-renders content, and interrupts its own in-flight smooth-scroll
    // animation on every dependency change. Scrolling the container to its
    // own current `scrollHeight` has no such target-drift problem: every
    // call unambiguously means "all the way down," so re-firing mid-
    // animation just continues toward the same endpoint instead of a moved
    // one.
    const el = scrollAreaRef.current
    if (!el) return
    // jsdom (this app's test environment) doesn't implement scrollTo — a
    // plain scrollTop assignment is a safe, equivalent (if non-smooth)
    // fallback there, and real browsers all support scrollTo.
    if (typeof el.scrollTo === 'function') {
      el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
    } else {
      el.scrollTop = el.scrollHeight
    }
  }, [messages, busy, decisionCenter])

  // The workspace banner needs a display-ready project (title, difficulty,
  // domain), not just the id the conversation stores — reuses the existing
  // /api/project/<id> lookup rather than inventing a second project shape.
  useEffect(() => {
    if (!selectedProjectId) {
      setSelectedProject(null)
      loadedProjectRef.current = null
      return
    }
    if (loadedProjectRef.current === selectedProjectId) return
    let cancelled = false
    api
      .getProject(selectedProjectId)
      .then(({ data }) => {
        if (cancelled) return
        setSelectedProject(data)
        loadedProjectRef.current = selectedProjectId
      })
      .catch(() => {
        /* Banner just stays hidden if the lookup fails — not worth an error state. */
      })
    return () => {
      cancelled = true
    }
  }, [selectedProjectId])

  // Keyed on selectedIdea's own id/name rather than the object itself —
  // `selectedIdea` gets a new object reference on every conversation
  // load/turn even when its content is unchanged, which would otherwise
  // refetch on every render instead of only on an actual selection change.
  const selectedIdeaKey = selectedIdea?.id ?? selectedIdea?.name ?? null
  useEffect(() => {
    if (!conversationId || (!selectedProjectId && !selectedIdeaKey)) {
      setDecisionCenter(null)
      setDecisionCenterLoading(false)
      setDecisionCenterError(false)
      return
    }
    let cancelled = false
    setDecisionCenterLoading(true)
    setDecisionCenterError(false)
    api
      .decisionCenter(conversationId)
      .then(({ data }) => {
        if (cancelled) return
        // A well-formed error payload (e.g. the selection was cleared
        // server-side between the turn and this fetch) is not "nothing
        // selected" — routing it through the same error branch as a failed
        // request avoids DecisionCenterBlock's own `data.error` guard
        // silently rendering nothing while decisionCenter is still truthy.
        if (data?.error) {
          setDecisionCenter(null)
          setDecisionCenterError(true)
        } else {
          setDecisionCenter(data)
        }
        setDecisionCenterLoading(false)
      })
      .catch(() => {
        if (cancelled) return
        setDecisionCenter(null)
        setDecisionCenterError(true)
        setDecisionCenterLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [conversationId, selectedProjectId, selectedIdeaKey])

  // The actual send — no auth check here on purpose, so it can be called
  // again post-login with the exact text that was gated, instead of routing
  // back through `send()` and risking a stale `user` closure re-opening the
  // modal it was just called from.
  const performSend = async (message, isAutoRetry = false) => {
    if (!isAutoRetry) {
      autoRetriedRef.current = false
      setInput('')
      setMessages((m) => [...m, { role: 'user', content: message }])
    }
    setBusy(true)
    setError(null)
    setFailedMessage(null)

    let retrying = false
    try {
      if (available) {
        let id = conversationIdRef.current
        if (!id) {
          const { data } = await api.createConversation()
          id = data.conversation_id
          // Set *before* changing the URL: the effect above fires the moment
          // conversationId changes, and needs to already see this as "loaded"
          // to skip the redundant, clobbering refetch (see that effect).
          loadedConversationRef.current = id
          setSearchParams({ c: id }, { replace: true })
        }
        const { data } = await api.sendConversationMessage(id, message)
        setMessages((m) => [...m, { role: 'assistant', content: data.reply, blocks: data.blocks }])
        setSelectedProjectId(data.selected_project_id ?? null)
        setSelectedIdea(data.selected_idea ?? null)
        // New conversation, new title on the first turn, or just a bumped
        // updated_at — the sidebar's Recents list needs to reflect any of
        // those right away rather than waiting on its poll.
        window.dispatchEvent(new Event('projectmind:conversations-changed'))
      } else {
        // No assistant configured — plain hybrid search, the same shape this
        // box had before an AI assistant existed at all.
        const { data } = await api.search({ query: message, top_k: 6 })
        const projects = data.filter((p) => (p.relevance?.score ?? 0) >= RELEVANCE_THRESHOLD)
        const content = projects.length > 0
          ? "Here's what I found:"
          : 'No strong matches — try describing the project differently.'
        const blocks = projects.length > 0 ? [{ type: 'project_recommendations', projects }] : []
        setMessages((m) => [...m, { role: 'assistant', content, blocks }])
      }
    } catch (err) {
      if (err.serverCode === 'LLM_RATE_LIMITED') {
        // Rate-limit gets its own wording, on purpose — the backend's own
        // message ("...try again shortly") is accurate but doesn't say the
        // one thing a student actually needs to hear: nothing was lost, this
        // is a shared, temporary provider limit, not a broken request. No
        // countdown here — the backend's bounded retry-after handling
        // (nlp/ai_assistant.py:_create_completion) never surfaces a duration
        // to this response, so a timer here would be invented, not real.
        if (!autoRetriedRef.current) {
          retrying = true
          autoRetriedRef.current = true
          setError('AI is temporarily busy. Your request was not lost — retrying automatically…')
          retryTimerRef.current = window.setTimeout(() => performSend(message, true), 4000)
        } else {
          setError('AI is still busy. Your request was not lost — try again in a moment.')
          setFailedMessage(message)
          // Roll back the optimistic user message so Retry doesn't duplicate
          // it — the message text itself is preserved and shown by
          // ComposerError below, so this never reads as "it disappeared."
          setMessages((m) => m.slice(0, -1))
        }
      } else {
        setError(err.message)
        setFailedMessage(message)
        setMessages((m) => m.slice(0, -1))
      }
    } finally {
      if (!retrying) setBusy(false)
    }
  }

  // Every message goes through this gate — a signed-out visitor gets the
  // same sign-in modal the landing page shows, and what they typed is held
  // (not lost) until they're in, then sent exactly as if the gate had never
  // been there.
  const send = (text = input) => {
    const message = text.trim()
    if (!message || busy) return
    if (!user) {
      setInput('')
      setGatedText(message)
      setAuthGateOpen(true)
      return
    }
    performSend(message)
  }

  // The [Select Project] button's direct path (POST .../select-project, no
  // LLM round-trip) — natural-language "select this project" reaches the
  // same server-side field via the select_project tool inside send() instead.
  const handleSelectProject = async (project) => {
    if (!conversationId) return
    setSelectedProjectId(project.project_id)
    // Selecting a catalogue project clears any active generated idea
    // server-side too (see routes/assistant.py) — mirrored here for
    // immediate feedback rather than waiting on the next fetch.
    setSelectedIdea(null)
    try {
      await api.selectProject(conversationId, project.project_id)
    } catch (err) {
      setError(err.message)
    }
  }

  // Lets another page (Resume Match, Ideate) hand off into an already-
  // selected conversation and have a first message fire automatically —
  // e.g. `/dashboard?c=<id>&autosend=Compare` — by reusing the exact same
  // send() the action chips already call, not a second send path. A value
  // matching a PROJECT_ACTIONS label sends that action's canned prompt
  // (unchanged behaviour); anything else is sent verbatim as a plain
  // message, which is what lets a page with no fixed action list (Ideate's
  // "Continue in AI Mentor") still open the thread on a specific question.
  const autosentRef = useRef(false)
  useEffect(() => {
    const label = searchParams.get('autosend')
    if (!label || autosentRef.current || loadingThread) return
    const action = PROJECT_ACTIONS.find((a) => a.label === label)
    const next = new URLSearchParams(searchParams)
    next.delete('autosend')
    setSearchParams(next, { replace: true })
    autosentRef.current = true
    send(action ? action.prompt : label)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams, loadingThread])

  const firstName = user?.name?.split(' ')[0]
  const showEmptyState = !loadingThread && messages.length === 0

  // Contextual follow-ups, shown only under the most recent turn — once the
  // conversation moves on, a chip suggesting "show easier ones" no longer
  // refers to anything on screen, so it should not linger under older turns.
  const lastMessage = messages[messages.length - 1]
  const lastProjects =
    !busy && lastMessage?.role === 'assistant' ? projectsFromBlocks(lastMessage.blocks) : []

  return (
    <div className="flex h-full flex-col">
      <div ref={scrollAreaRef} className="flex flex-1 flex-col overflow-y-auto px-4 py-6">
        {loadingThread ? (
          <div className="flex flex-1 items-center justify-center">
            <Spinner label="Loading conversation…" />
          </div>
        ) : showEmptyState ? (
          <div className="relative flex flex-1 flex-col items-center justify-center px-4 pb-8 text-center">
            <EmptyStateBackdrop />
            <div className="relative z-10 w-full max-w-5xl">
              <h2 className="t-headline-lg mb-3" style={{ color: 'var(--primary)' }}>
                {firstName ? `Welcome back, ${firstName}.` : 'Ready when you are.'}
              </h2>
              <p className="t-body-md" style={{ color: 'var(--outline)' }}>
                What are you building today?
              </p>
            </div>
          </div>
        ) : (
          <div className="mx-auto w-full max-w-3xl flex-1 space-y-5">
            {messages.map((m, i) => (
              <Bubble
                key={i}
                role={m.role}
                content={m.content}
                blocks={m.blocks}
                conversationId={conversationId}
                selectedProjectId={selectedProjectId}
                onSelectProject={handleSelectProject}
                onAction={send}
              />
            ))}
            {busy && <TypingDots />}
            {lastProjects.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {CONTEXTUAL_SUGGESTIONS.map((q) => (
                  <button
                    key={q}
                    type="button"
                    onClick={() => send(q)}
                    className="t-label-mono px-3 py-1.5 transition hover:opacity-80"
                    style={{ border: '1px solid var(--border-technical)', color: 'var(--on-surface-variant)', fontSize: 12, borderRadius: 999 }}
                  >
                    {q}
                  </button>
                ))}
              </div>
            )}
            {/* Deliberately NOT gated on `!busy` (unlike the message list
                above it) — this whole area is the persistent "which project/
                idea am I working on, what's next" hub, not part of the
                turn-by-turn reply stream. Hiding it every time any unrelated
                follow-up question was in flight made the one anchor meant to
                give this workflow continuity flicker away and back on almost
                every turn — exactly the "disconnected blocks" feeling this
                task exists to fix. `send()` itself already no-ops while
                `busy` (see its own guard), so nothing here risks a double
                submit by staying visible. */}
            {(selectedProjectId || selectedIdea) && decisionCenter && (
              <DecisionCenterBlock data={decisionCenter} onAction={send} />
            )}
            {/* While the read-only Decision Center fetch is in flight, show
                its own loading card instead of the plain chip fallback below
                — the two would otherwise flash one after another for every
                selection. */}
            {(selectedProjectId || selectedIdea) && !decisionCenter && decisionCenterLoading && (
              <DecisionCenterLoading />
            )}
            {/* Quiet, non-alarming note when the summary genuinely failed to
                load (as opposed to just not having run yet) — the chip
                fallback right below still works either way, this just says
                why the richer card isn't there instead of leaving it
                unexplained. */}
            {(selectedProjectId || selectedIdea) && !decisionCenter && !decisionCenterLoading && decisionCenterError && (
              <p className="t-label-mono" style={{ color: 'var(--outline)', fontSize: 11 }}>
                Couldn't load the full decision summary — quick actions still work below.
              </p>
            )}
            {/* The plain action-chip rows are the fallback once the Decision
                Center fetch has settled without data — either it hasn't run
                yet for this selection, or it failed (decisionCenterError) —
                same underlying canned prompts, just without the richer
                context around them. Never shown while decisionCenter itself
                is loaded, or while its fetch is still in flight. Create
                Roadmap is styled as the primary action here (filled), same
                Primary/Secondary distinction Decision Center's own action
                rows already use, so the hierarchy reads the same whichever
                of the two is on screen. */}
            {selectedProjectId && !decisionCenter && !decisionCenterLoading && (
              <div className="flex flex-wrap gap-2">
                {PROJECT_ACTIONS.map((action) => (
                  <button
                    key={action.label}
                    type="button"
                    onClick={() => send(action.prompt)}
                    className="t-label-caps px-3 py-1.5 transition hover:opacity-80"
                    style={
                      action.label === 'Create Roadmap'
                        ? { background: 'var(--primary)', color: 'var(--on-primary)', fontSize: 10.5, borderRadius: 999 }
                        : { border: '1px solid var(--primary)', color: 'var(--primary)', fontSize: 10.5, borderRadius: 999 }
                    }
                  >
                    {action.label}
                  </button>
                ))}
              </div>
            )}
            {!selectedProjectId && selectedIdea && !decisionCenter && !decisionCenterLoading && (
              <div className="flex flex-wrap gap-2">
                {IDEA_BUILD_ACTIONS.map((action) => (
                  <button
                    key={action.label}
                    type="button"
                    onClick={() => send(action.prompt)}
                    className="t-label-caps px-3 py-1.5 transition hover:opacity-80"
                    style={
                      action.label === 'Create Roadmap'
                        ? { background: 'var(--primary)', color: 'var(--on-primary)', fontSize: 10.5, borderRadius: 999 }
                        : { border: '1px solid var(--primary)', color: 'var(--primary)', fontSize: 10.5, borderRadius: 999 }
                    }
                  >
                    {action.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Always pinned to the bottom of the viewport — correct chat UX
          (always reachable regardless of scroll position), and it's what
          keeps the empty state's greeting centered above rather than the
          composer trailing right underneath it. */}
      <div className="mx-auto w-full max-w-3xl shrink-0 px-6 pb-8">
        {selectedProject ? <ActiveProjectBanner project={selectedProject} /> : <ActiveIdeaBanner idea={selectedIdea} />}
        <ComposerError error={error} failedMessage={failedMessage} onRetry={() => send(failedMessage)} />
        <Composer
          input={input}
          setInput={setInput}
          send={send}
          busy={busy}
          voiceSupported={voiceSupported}
          listening={listening}
          start={start}
          stop={stop}
          composerRef={composerRef}
        />
        {showEmptyState && (
          <div className="mt-5">
            <p className="t-label-caps mb-2 text-center" style={{ color: 'var(--outline)', fontSize: 9.5 }}>
              Try ProjectMind
            </p>
            <div className="flex flex-wrap justify-center gap-2">
              {STARTERS.map((example) => (
                <button
                  key={example}
                  type="button"
                  onClick={() => send(example)}
                  className="t-label-mono whitespace-nowrap px-3 py-1.5 transition hover:opacity-80"
                  style={{ border: '1px solid var(--border-technical)', color: 'var(--on-surface-variant)', fontSize: 12, borderRadius: 999 }}
                >
                  {example}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      <AuthGateModal
        open={authGateOpen}
        onClose={() => {
          setAuthGateOpen(false)
          setGatedText('')
        }}
        onAuthenticated={() => {
          setAuthGateOpen(false)
          const text = gatedText
          setGatedText('')
          if (text) performSend(text)
        }}
        message="Sign in to search and chat with ProjectMind — your message will send right after."
      />
    </div>
  )
}
