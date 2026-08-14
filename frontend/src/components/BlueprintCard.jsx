import { Link } from 'react-router-dom'

// Only the four secondary actions get an icon here — Select is rendered
// separately below as the card's one primary call-to-action.
const ACTION_ICON = {
  improve: 'edit',
  uniqueness: 'verified',
  compare: 'compare_arrows',
  roadmap: 'map',
}

/**
 * Ideate.jsx's own idea-card layout — a percentage badge, icon meta row, and
 * inline action links, distinct from GeneratedIdeaCard's pill-badge
 * treatment (which Dashboard.jsx's chat bubbles keep using unchanged; this
 * component exists so restyling this one page never touches that shared
 * one). Same idea shape and `actions` contract as GeneratedIdeaCard —
 * `actions` is `{ key, label, onClick, active?, primary?, disabled? }[]`,
 * with the `key: 'select'` entry singled out as the card's primary CTA.
 *
 * Only ever shows `originality_score` (real, from nlp/ideation.py's
 * validation pass) — never a second, fabricated "feasibility" figure the
 * backend doesn't compute.
 */
export default function BlueprintCard({ idea, actions = [], selected = false }) {
  const closest = idea.similar_projects?.[0]
  const selectAction = actions.find((a) => a.key === 'select')
  const linkActions = actions.filter((a) => a.key !== 'select')

  return (
    <div
      className="glass-panel w-full max-w-full p-4"
      style={{ borderRadius: 8, border: `1px solid ${selected ? 'var(--primary)' : 'var(--border-technical)'}` }}
    >
      <div className="flex items-start gap-3">
        <div
          className="flex shrink-0 flex-col items-center justify-center gap-1 py-2.5"
          style={{ width: 60, background: 'var(--surface-container-highest)', border: '1px solid var(--border-technical)', borderRadius: 8 }}
        >
          <span className="t-label-mono" style={{ color: 'var(--primary)', fontSize: 17, fontWeight: 700, lineHeight: 1 }}>
            {idea.originality_score}%
          </span>
          <span className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 7.5, lineHeight: 1 }}>
            Originality
          </span>
        </div>

        <div className="min-w-0 flex-1">
          <Link
            to="/idea"
            state={{ idea }}
            className="t-label-mono block transition hover:opacity-75"
            style={{ color: 'var(--on-surface)', fontSize: 15 }}
            title="Open this idea's full workspace"
          >
            {idea.name}
          </Link>
          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="t-label-mono flex items-center gap-1" style={{ color: 'var(--outline)', fontSize: 11 }}>
              <span className="material-symbols-outlined" style={{ fontSize: 12 }}>speed</span>
              {idea.difficulty}
            </span>
            <span className="t-label-mono flex items-center gap-1" style={{ color: 'var(--outline)', fontSize: 11 }}>
              <span className="material-symbols-outlined" style={{ fontSize: 12 }}>category</span>
              {idea.domain}
            </span>
            <span className="t-label-mono flex items-center gap-1" style={{ color: 'var(--outline)', fontSize: 11 }}>
              <span className="material-symbols-outlined" style={{ fontSize: 12 }}>schedule</span>
              ~{idea.duration_weeks} weeks
            </span>
          </div>
        </div>
      </div>

      <div className="mt-3 space-y-1.5">
        <p className="t-body-md" style={{ color: 'var(--on-surface-variant)', fontSize: 12.5 }}>
          <span style={{ color: 'var(--on-surface)', fontWeight: 600 }}>Problem: </span>
          {idea.problem}
        </p>
        <p className="t-body-md" style={{ color: 'var(--on-surface-variant)', fontSize: 12.5 }}>
          <span style={{ color: 'var(--on-surface)', fontWeight: 600 }}>Solution: </span>
          {idea.solution}
        </p>
        {idea.unique_point && (
          <p className="t-body-md" style={{ color: 'var(--on-surface-variant)', fontSize: 12.5 }}>
            <span style={{ color: 'var(--on-surface)', fontWeight: 600 }}>Why it's different: </span>
            {idea.unique_point}
          </p>
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
        <p className="t-label-mono mt-3" style={{ color: 'var(--outline)', fontSize: 10.5 }}>
          Closest existing project:{' '}
          <Link to={`/project/${closest.project_id}`} className="transition hover:opacity-75" style={{ color: 'var(--primary)' }}>
            {closest.title}
          </Link>
          {' '}({Math.round((closest.similarity ?? 0) * 100)}% similar)
        </p>
      )}

      {(linkActions.length > 0 || selectAction) && (
        <div
          className="mt-3.5 flex flex-wrap items-center justify-between gap-3 pt-3"
          style={{ borderTop: '1px solid var(--border-technical)' }}
        >
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            {linkActions.map((action) => (
              <button
                key={action.key ?? action.label}
                type="button"
                onClick={action.onClick}
                disabled={action.disabled}
                className="t-label-caps flex items-center gap-1.5 transition hover:opacity-75 disabled:opacity-40"
                style={{ color: action.active ? 'var(--primary)' : 'var(--on-surface-variant)', fontSize: 10.5 }}
              >
                <span className="material-symbols-outlined" style={{ fontSize: 14 }}>
                  {ACTION_ICON[action.key] ?? 'chevron_right'}
                </span>
                {action.label}
              </button>
            ))}
          </div>
          {selectAction && (
            <button
              type="button"
              onClick={selectAction.onClick}
              disabled={selectAction.disabled}
              className="t-label-caps shrink-0 px-3.5 py-1.5 transition hover:opacity-80 disabled:opacity-50"
              style={
                selectAction.primary
                  ? { background: 'var(--primary)', color: 'var(--on-primary)', borderRadius: 6, fontSize: 10.5 }
                  : { border: '1px solid var(--border-technical)', color: 'var(--on-surface-variant)', borderRadius: 6, fontSize: 10.5 }
              }
            >
              {selectAction.label}
            </button>
          )}
        </div>
      )}
    </div>
  )
}
