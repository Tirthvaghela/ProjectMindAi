import Panel from './Panel'

/**
 * Phase-by-phase "how to start" plan for an idea that has no project_id of
 * its own (backend/nlp/generator.py:phase_plan + domain_profile, surfaced via
 * recommend.check_uniqueness's `getting_started` field — the exact same
 * REST endpoint /api/uniqueness already exposes, not a second engine).
 * Template-based on domain, not model-generated: nothing here is invented
 * beyond the domain's standard phase/module breakdown, so it works with no
 * AI assistant configured. Shared by pages/UniquenessCheck.jsx and
 * pages/Ideate.jsx (the AI ideation workspace's "getting started" preview
 * on a generated idea) so this composition is defined once.
 */
export default function GettingStartedPanel({ plan }) {
  const max = Math.max(...plan.phases.map((p) => p.weeks), 1)
  return (
    <Panel
      icon="route"
      title="Getting started"
      description="A first-draft build plan for your idea, based on how similar projects in this domain are usually scoped."
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="gm-chip px-2 py-1">
          {plan.domain || 'General'}{plan.domain_is_estimate ? ' (estimated)' : ''}
        </span>
        <span className="t-label-mono" style={{ color: 'var(--outline)', fontSize: 12 }}>
          ~{plan.estimated_weeks} week{plan.estimated_weeks === 1 ? '' : 's'} end to end
        </span>
      </div>

      {plan.technologies?.length > 0 && (
        <div className="mt-4">
          <p className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>Suggested stack</p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {plan.technologies.map((t) => (
              <span key={t} className="gm-chip px-2 py-1">{t}</span>
            ))}
          </div>
        </div>
      )}

      {plan.modules?.length > 0 && (
        <div className="mt-4">
          <p className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>Typical modules for this domain</p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {plan.modules.map((m) => (
              <span key={m} className="gm-chip px-2 py-1">{m}</span>
            ))}
          </div>
        </div>
      )}

      <ol className="mt-5 space-y-4">
        {plan.phases.map((phase, index) => (
          <li key={phase.phase} className="flex gap-3">
            <div className="flex flex-col items-center">
              <span
                className="t-label-mono grid h-6 w-6 shrink-0 place-items-center rounded-full"
                style={{ background: 'var(--surface-container-highest)', color: 'var(--on-surface)', fontSize: 11 }}
              >
                {index + 1}
              </span>
              {index < plan.phases.length - 1 && (
                <span className="mt-1 w-px flex-1" style={{ background: 'var(--border-technical)' }} />
              )}
            </div>
            <div className="min-w-0 flex-1 pb-1">
              <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                <p className="t-label-mono" style={{ color: 'var(--on-surface)' }}>{phase.phase}</p>
                <span className="t-label-mono shrink-0 tabular-nums" style={{ color: 'var(--on-surface-variant)', fontSize: 12 }}>
                  {phase.weeks} wk{phase.weeks === 1 ? '' : 's'}
                </span>
              </div>
              <p className="t-body-md mt-0.5" style={{ color: 'var(--on-surface-variant)', fontSize: 13.5 }}>{phase.description}</p>
              <div className="mt-2 h-1.5 overflow-hidden rounded-full" style={{ background: 'var(--surface-container-high)' }}>
                <div className="h-full rounded-full" style={{ background: 'var(--primary)', width: `${(phase.weeks / max) * 100}%` }} />
              </div>
            </div>
          </li>
        ))}
      </ol>

      <p className="t-label-mono mt-4" style={{ color: 'var(--outline)', fontSize: 11 }}>
        A starting point, not a spec — durations and modules follow the domain's usual shape and adjust as your idea takes form.
      </p>
    </Panel>
  )
}
