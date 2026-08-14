import { useState } from 'react'
import { motion } from 'framer-motion'
import { Spinner } from './Feedback'
import Panel from './Panel'
import { synopsisToPdf, roadmapToPdf, milestonesToPdf } from '../utils/pdf'

/**
 * Plain-text rendering of a synopsis, for the "Copy" button.
 *
 * A student pastes this straight into a report draft, so it is formatted as
 * a document outline (headings + numbered/bulleted lines), not JSON.
 */
function synopsisAsText(s) {
  const list = (items) => items.map((item) => `- ${item}`).join('\n')
  return [
    `${s.title}`,
    '',
    'ABSTRACT',
    s.abstract,
    '',
    'PROBLEM STATEMENT',
    s.problem_statement,
    '',
    'OBJECTIVES',
    list(s.objectives),
    '',
    'SCOPE',
    s.scope,
    '',
    'METHODOLOGY',
    list(s.methodology),
    '',
    'MODULES',
    list(s.modules),
    '',
    'TECHNOLOGY STACK',
    s.technology_stack.join(', '),
    '',
    'EXPECTED RESULTS',
    list(s.expected_results),
    '',
    'FUTURE SCOPE',
    list(s.future_scope),
  ].join('\n')
}

function Section({ title, children }) {
  return (
    <div className="pt-4 first:pt-0" style={{ borderTop: '1px solid var(--border-technical)' }}>
      <h3 className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>{title}</h3>
      <div className="t-body-md mt-1.5" style={{ color: 'var(--on-surface-variant)' }}>{children}</div>
    </div>
  )
}

function BulletList({ items }) {
  return (
    <ul className="space-y-1.5">
      {items.map((item, i) => (
        <li key={i} className="flex gap-2">
          <span className="mt-2 h-1 w-1 shrink-0 rounded-full" style={{ background: 'var(--primary)' }} />
          <span>{item}</span>
        </li>
      ))}
    </ul>
  )
}

function Chips({ items }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((item) => (
        <span key={item} className="gm-chip px-2 py-1">
          {item}
        </span>
      ))}
    </div>
  )
}

export function SynopsisView({ synopsis }) {
  const [copied, setCopied] = useState(false)

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(synopsisAsText(synopsis))
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      /* Clipboard permission denied — the text is still on screen to select manually. */
    }
  }

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <p className="t-label-mono" style={{ color: 'var(--outline)', fontSize: 11 }}>
          A first draft, generated from this project's own fields — edit freely.
        </p>
        <div className="flex shrink-0 gap-2">
          <button onClick={copy} className="btn-secondary t-label-caps px-3 py-1.5">
            {copied ? 'Copied ✓' : 'Copy as text'}
          </button>
          <button onClick={() => synopsisToPdf(synopsis)} className="btn-secondary t-label-caps px-3 py-1.5">
            Download PDF
          </button>
        </div>
      </div>

      <Section title="Abstract">{synopsis.abstract}</Section>
      <Section title="Problem statement">{synopsis.problem_statement}</Section>
      <Section title="Objectives"><BulletList items={synopsis.objectives} /></Section>
      <Section title="Scope">{synopsis.scope}</Section>
      <Section title="Methodology"><BulletList items={synopsis.methodology} /></Section>
      <Section title="Modules"><Chips items={synopsis.modules} /></Section>
      <Section title="Technology stack"><Chips items={synopsis.technology_stack} /></Section>
      <Section title="Expected results"><BulletList items={synopsis.expected_results} /></Section>
      <Section title="Future scope"><BulletList items={synopsis.future_scope} /></Section>
    </motion.div>
  )
}

const EXPERIENCE_LEVELS = ['', 'Beginner', 'Intermediate', 'Advanced']

/**
 * Team-size + experience controls that re-plan the same phase list against a
 * personalised duration (`onPersonalize`, e.g. POST /api/timeline-predict
 * for a catalogue project or POST /api/idea/timeline for a generated idea —
 * see RoadmapView below) instead of the flat baseline. Kept inside the
 * Roadmap tab rather than a separate tab — it's the same phase list, just
 * re-sized, not a different feature.
 */
function TimelineControls({ onPersonalize, onResult }) {
  const [teamSize, setTeamSize] = useState(1)
  const [experienceLevel, setExperienceLevel] = useState('')
  const [busy, setBusy] = useState(false)

  const recalculate = async () => {
    setBusy(true)
    try {
      const { data } = await onPersonalize({ teamSize, experienceLevel })
      onResult(data)
    } catch {
      /* Leave the baseline roadmap showing — personalising is an enhancement, not required. */
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mb-4 flex flex-wrap items-end gap-3 p-3" style={{ background: 'var(--surface-container-low)', borderRadius: 8 }}>
      <label className="text-xs">
        <span className="t-label-caps mb-1 block" style={{ color: 'var(--outline)', fontSize: 10 }}>Team size</span>
        <input
          type="number"
          min={1}
          max={20}
          value={teamSize}
          onChange={(e) => setTeamSize(Math.max(1, Math.min(20, Number(e.target.value) || 1)))}
          className="gm-input w-16 px-2 py-1.5 text-sm"
        />
      </label>
      <label className="text-xs">
        <span className="t-label-caps mb-1 block" style={{ color: 'var(--outline)', fontSize: 10 }}>Your experience</span>
        <select
          value={experienceLevel}
          onChange={(e) => setExperienceLevel(e.target.value)}
          className="gm-input px-2 py-1.5 text-sm"
        >
          {EXPERIENCE_LEVELS.map((level) => (
            <option key={level} value={level}>{level || 'Same as project'}</option>
          ))}
        </select>
      </label>
      <button onClick={recalculate} disabled={busy} className="btn-primary t-label-caps px-3 py-1.5">
        {busy ? 'Calculating…' : 'Personalize estimate'}
      </button>
    </div>
  )
}

export function RoadmapView({ roadmap, onPersonalize }) {
  const [personal, setPersonal] = useState(null)
  const totalWeeks = personal?.predicted_weeks ?? roadmap.total_weeks
  // /api/timeline-predict re-plans weeks against a personalised duration but
  // (deliberately — see backend/nlp/timeline.py) doesn't carry the task-level
  // detail roadmap_for() adds, since "how long will it take" and "what do I
  // build" are different questions. The phase list is the same fixed 7-phase
  // template either way though (same names, same order, same count — only
  // the week split changes), so merge by index: personalised weeks/
  // description, but the baseline roadmap's tasks/technologies/output.
  const phases = personal
    ? personal.phases.map((phase, i) => ({ ...roadmap.phases[i], ...phase }))
    : roadmap.phases
  const max = Math.max(...phases.map((p) => p.weeks), 1)

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
      <TimelineControls onPersonalize={onPersonalize} onResult={setPersonal} />

      <div className="flex flex-wrap items-start justify-between gap-3">
        <p className="t-label-mono" style={{ color: 'var(--outline)', fontSize: 11 }}>
          {personal ? (
            <>
              Personalised estimate: <span style={{ color: 'var(--on-surface-variant)' }}>{totalWeeks} week{totalWeeks === 1 ? '' : 's'}</span>
              {' '}(baseline {personal.base_weeks} week{personal.base_weeks === 1 ? '' : 's'}), split across {phases.length} phases.
            </>
          ) : (
            <>{totalWeeks} week{totalWeeks === 1 ? '' : 's'} total, split across {phases.length} phases.</>
          )}
        </p>
        <button
          onClick={() => roadmapToPdf({ title: roadmap.title, total_weeks: totalWeeks, phases })}
          className="btn-secondary t-label-caps shrink-0 px-3 py-1.5"
        >
          Download PDF
        </button>
      </div>

      {personal && (
        <ul className="t-label-mono mt-2 space-y-0.5" style={{ color: 'var(--outline)', fontSize: 11 }}>
          {personal.factors.map((f) => (
            <li key={f.factor}>· {f.note}</li>
          ))}
        </ul>
      )}

      <ol className="mt-4 space-y-4">
        {phases.map((phase, index) => (
          <li key={phase.phase} className="flex gap-3">
            <div className="flex flex-col items-center">
              <span
                className="t-label-mono grid h-6 w-6 shrink-0 place-items-center rounded-full"
                style={{ background: 'var(--surface-container-highest)', color: 'var(--on-surface)', fontSize: 11 }}
              >
                {index + 1}
              </span>
              {index < phases.length - 1 && (
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
                <motion.div
                  className="h-full rounded-full"
                  style={{ background: 'var(--primary)' }}
                  initial={{ width: 0 }}
                  animate={{ width: `${(phase.weeks / max) * 100}%` }}
                  transition={{ duration: 0.5, delay: index * 0.05 }}
                />
              </div>

              {phase.tasks?.length > 0 && (
                <ul className="t-body-md mt-2.5 space-y-1" style={{ color: 'var(--on-surface-variant)', fontSize: 12.5 }}>
                  {phase.tasks.map((task) => (
                    <li key={task} className="flex gap-1.5">
                      <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full" style={{ background: 'var(--outline)' }} />
                      <span>{task}</span>
                    </li>
                  ))}
                </ul>
              )}

              {phase.technologies?.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {phase.technologies.map((t) => (
                    <span key={t} className="t-label-mono px-1.5 py-0.5" style={{ border: '1px solid var(--border-technical)', color: 'var(--on-surface-variant)', fontSize: 10.5, borderRadius: 4 }}>
                      {t}
                    </span>
                  ))}
                </div>
              )}

              {phase.expected_output && (
                <p className="t-label-mono mt-2" style={{ color: 'var(--outline)', fontSize: 11.5 }}>
                  Output: {phase.expected_output}
                </p>
              )}
            </div>
          </li>
        ))}
      </ol>
    </motion.div>
  )
}

/**
 * [Milestones] result — one checkpoint per roadmap phase, derived directly
 * from it (backend/nlp/generator.py:milestones_for) so a milestone's week can
 * never disagree with the roadmap's own phase weeks.
 */
export function MilestonesView({ milestones }) {
  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <p className="t-label-mono" style={{ color: 'var(--outline)', fontSize: 11 }}>
          {milestones.milestones.length} checkpoints across {milestones.total_weeks} week
          {milestones.total_weeks === 1 ? '' : 's'}.
        </p>
        <button
          onClick={() => milestonesToPdf(milestones)}
          className="btn-secondary t-label-caps shrink-0 px-3 py-1.5"
        >
          Download PDF
        </button>
      </div>
      <ol className="mt-4 space-y-3">
        {milestones.milestones.map((m) => (
          <li key={m.id} className="flex items-center gap-3">
            <span
              className="t-label-mono grid h-6 w-10 shrink-0 place-items-center rounded-full"
              style={{ background: 'var(--surface-container-highest)', color: 'var(--on-surface)', fontSize: 10.5 }}
            >
              {m.id}
            </span>
            <span className="t-body-md flex-1" style={{ color: 'var(--on-surface-variant)', fontSize: 13.5 }}>
              {m.title}
            </span>
            <span className="t-label-mono shrink-0 tabular-nums" style={{ color: 'var(--outline)', fontSize: 12 }}>
              wk {m.week}
            </span>
          </li>
        ))}
      </ol>
    </motion.div>
  )
}

/**
 * Synopsis + roadmap + milestones, fetched on demand.
 *
 * All three are cheap, deterministic template output (see
 * backend/nlp/generator.py) — fetched lazily per tab rather than eagerly on
 * page load, matching the on-demand pattern SkillGap and the uniqueness
 * checker already use elsewhere in this app, so a project detail page that
 * nobody plans doesn't pay for it.
 *
 * `fetchers` is `{ synopsis, roadmap, milestones, timeline }`, each an async
 * function returning the same `{data}` shape api.js's own calls resolve to —
 * this is what lets pages/ProjectDetail.jsx (catalogue project, keyed by
 * project_id) and pages/IdeaDetail.jsx (a generated idea, no project_id —
 * see backend/routes/ideas.py) share this exact component instead of
 * forking it, each just wiring the four calls to its own endpoints.
 */
export default function ProjectPlanner({ fetchers }) {
  const [tab, setTab] = useState('synopsis')
  const [synopsis, setSynopsis] = useState(null)
  const [roadmap, setRoadmap] = useState(null)
  const [milestones, setMilestones] = useState(null)
  const [status, setStatus] = useState({ synopsis: 'idle', roadmap: 'idle', milestones: 'idle' })

  const load = async (which) => {
    if (status[which] === 'loading' || status[which] === 'done') return
    setStatus((s) => ({ ...s, [which]: 'loading' }))
    try {
      if (which === 'synopsis') setSynopsis((await fetchers.synopsis()).data)
      else if (which === 'roadmap') setRoadmap((await fetchers.roadmap()).data)
      else setMilestones((await fetchers.milestones()).data)
      setStatus((s) => ({ ...s, [which]: 'done' }))
    } catch {
      setStatus((s) => ({ ...s, [which]: 'error' }))
    }
  }

  const selectTab = (which) => {
    setTab(which)
    load(which)
  }

  const tabSwitcher = (
    <div className="flex shrink-0 items-center gap-0.5 p-1" style={{ background: 'var(--surface-container-low)', borderRadius: 10 }}>
      {[
        ['synopsis', 'Synopsis'],
        ['roadmap', 'Roadmap'],
        ['milestones', 'Milestones'],
      ].map(([key, label]) => (
        <button
          key={key}
          onClick={() => selectTab(key)}
          className="t-label-caps px-3 py-1.5 transition"
          style={
            tab === key
              ? { background: 'var(--primary)', color: 'var(--on-primary)', borderRadius: 8 }
              : { color: 'var(--on-surface-variant)', borderRadius: 8 }
          }
        >
          {label}
        </button>
      ))}
    </div>
  )

  const labels = { synopsis: 'Drafting synopsis…', roadmap: 'Planning roadmap…', milestones: 'Building milestones…' }

  return (
    <Panel
      icon="route"
      title="Plan this project"
      description="A generated synopsis draft, a week-by-week build roadmap, and build milestones."
      actions={tabSwitcher}
    >
      {tab === 'synopsis' && status.synopsis === 'idle' && (
        <button onClick={() => load('synopsis')} className="btn-primary t-label-caps px-4 py-2">
          Generate synopsis
        </button>
      )}
      {tab === 'milestones' && status.milestones === 'idle' && (
        <button onClick={() => load('milestones')} className="btn-primary t-label-caps px-4 py-2">
          Generate milestones
        </button>
      )}
      {tab === 'roadmap' && status.roadmap === 'idle' && (
        <button onClick={() => load('roadmap')} className="btn-primary t-label-caps px-4 py-2">
          Generate roadmap
        </button>
      )}

      {status[tab] === 'loading' && <Spinner label={labels[tab]} />}
      {status[tab] === 'error' && (
        <p className="t-body-md" style={{ color: '#ffb4ab', fontSize: 13 }}>Could not generate this — try again.</p>
      )}

      {tab === 'synopsis' && status.synopsis === 'done' && synopsis && <SynopsisView synopsis={synopsis} />}
      {tab === 'roadmap' && status.roadmap === 'done' && roadmap && (
        <RoadmapView roadmap={roadmap} onPersonalize={fetchers.timeline} />
      )}
      {tab === 'milestones' && status.milestones === 'done' && milestones && (
        <MilestonesView milestones={milestones} />
      )}
    </Panel>
  )
}
