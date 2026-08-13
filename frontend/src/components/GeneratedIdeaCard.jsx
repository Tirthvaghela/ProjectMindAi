import { Link } from 'react-router-dom'

/**
 * One AI-generated project concept (backend/nlp/ideation.py, surfaced via
 * nlp/chat_tools.py:generate_project_ideas / refine_project_idea — the
 * "AI Ideation Engine"). Deliberately NOT ProjectCard/MiniProjectCard: a
 * generated idea has no project_id and is not in the catalogue, and must
 * never be presented as though it were. Already run through the existing
 * uniqueness checker before this card exists, so its originality score and
 * closest-existing-project link are both real, not decoration.
 *
 * Shared by Dashboard.jsx (chat bubbles) and pages/Ideate.jsx (the dedicated
 * ideation workspace) so the "AI Generated Project Idea" treatment — the one
 * visual cue that separates an invented concept from a catalogue project —
 * is defined in exactly one place.
 *
 * `actions` is a list of { key, label, onClick, busy? } — each surface wires
 * up whichever actions make sense for its own context rather than this
 * component hard-coding one fixed set.
 */
export default function GeneratedIdeaCard({ idea, actions, selected = false, busy = false }) {
  const closest = idea.similar_projects?.[0]

  return (
    <div
      className="glass-panel relative w-full max-w-full p-4"
      style={{ borderRadius: 8, border: `1px solid ${selected ? 'var(--primary)' : 'var(--primary)'}`, opacity: busy ? 0.6 : 1 }}
    >
      {busy && (
        <div className="absolute inset-0 z-10 grid place-items-center" style={{ background: 'rgba(0,0,0,0.55)', borderRadius: 8 }}>
          <div
            className="h-6 w-6 animate-spin rounded-full border-2"
            style={{ borderColor: 'var(--border-technical)', borderTopColor: 'var(--primary)' }}
          />
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2">
        <span
          className="t-label-caps px-2 py-1"
          style={{ background: 'var(--primary)', color: 'var(--on-primary)', borderRadius: 999, fontSize: 9.5 }}
        >
          AI Generated Project Idea
        </span>
        <span className="t-label-mono shrink-0 tabular-nums" style={{ color: idea.is_unique ? 'var(--primary)' : 'var(--outline)', fontSize: 12 }}>
          {idea.originality_score}% original
        </span>
      </div>

      <h3 className="t-label-mono mt-2.5" style={{ color: 'var(--on-surface)', fontSize: 15 }}>{idea.name}</h3>
      <p className="t-label-mono mt-0.5" style={{ color: 'var(--outline)', fontSize: 11.5 }}>
        {idea.difficulty} · {idea.domain} · ~{idea.duration_weeks} weeks
      </p>

      <div className="mt-3 space-y-2">
        <div>
          <p className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 9.5 }}>Problem</p>
          <p className="t-body-md" style={{ color: 'var(--on-surface-variant)', fontSize: 12.5 }}>{idea.problem}</p>
        </div>
        <div>
          <p className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 9.5 }}>Solution</p>
          <p className="t-body-md" style={{ color: 'var(--on-surface-variant)', fontSize: 12.5 }}>{idea.solution}</p>
        </div>
        {idea.unique_point && (
          <div>
            <p className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 9.5 }}>Why it's different</p>
            <p className="t-body-md" style={{ color: 'var(--on-surface-variant)', fontSize: 12.5 }}>{idea.unique_point}</p>
          </div>
        )}
      </div>

      {idea.technologies?.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {idea.technologies.map((t) => (
            <span key={t} className="gm-chip px-2 py-1">{t}</span>
          ))}
        </div>
      )}

      {closest && (
        <p className="t-label-mono mt-3" style={{ color: 'var(--outline)', fontSize: 11 }}>
          Closest existing project:{' '}
          <Link to={`/project/${closest.project_id}`} className="transition hover:opacity-75" style={{ color: 'var(--primary)' }}>
            {closest.title}
          </Link>
          {' '}({Math.round((closest.similarity ?? 0) * 100)}% similar)
        </p>
      )}

      {actions?.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {actions.map((action) => (
            <button
              key={action.key ?? action.label}
              type="button"
              onClick={action.onClick}
              disabled={busy || action.disabled}
              className="t-label-caps px-2.5 py-1.5 transition hover:opacity-80 disabled:opacity-50"
              style={
                action.primary
                  ? { background: 'var(--primary)', color: 'var(--on-primary)', borderRadius: 6, fontSize: 10 }
                  : { border: `1px solid ${action.active ? 'var(--primary)' : 'var(--border-technical)'}`, color: action.active ? 'var(--primary)' : 'var(--on-surface-variant)', borderRadius: 6, fontSize: 10 }
              }
            >
              {action.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
