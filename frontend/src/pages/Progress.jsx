import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import useAuth from '../hooks/useAuth.jsx'
import api from '../services/api'
import PageHeader from '../components/PageHeader'
import Panel from '../components/Panel'
import { Spinner, ErrorNotice, EmptyState } from '../components/Feedback'

const muted = { color: 'var(--on-surface-variant)' }
const STATUS_LABEL = { completed: 'Completed', in_progress: 'In progress', not_started: 'Not started', none: 'No recorded progress' }
const KIND_LABEL = { learn: 'Learn', improve: 'Practise', confirm: 'Check', prerequisite: 'Foundation', concepts: 'Pick up while building' }

function Chip({ children }) {
  return (
    <span
      className="t-label-mono inline-flex items-center gap-1.5 px-2.5 py-1"
      style={{ border: '1px solid var(--border-technical)', borderRadius: 999, fontSize: 12, color: 'var(--on-surface)' }}
    >
      {children}
    </span>
  )
}

function formatDate(iso) {
  if (!iso) return 'date not recorded'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? 'date not recorded' : d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

function Provenance({ children }) {
  return (
    <p className="t-body-md mb-3" style={{ ...muted, fontSize: 12 }}>
      {children}
    </p>
  )
}

function LinkButton({ to, children }) {
  return (
    <Link to={to} className="t-label-caps inline-block px-3 py-1.5" style={{ background: 'var(--primary)', color: 'var(--on-primary)', borderRadius: 8, fontSize: 11 }}>
      {children}
    </Link>
  )
}

function ProfileSection({ profile, skills }) {
  const levels = Object.entries(profile.level_counts)
  return (
    <Panel icon="person" title="Your profile (self-reported)" aria-label="Profile summary" as="section">
      <div className="mt-4">
        <Provenance>What you entered on your profile. Levels are your own and are not verified.</Provenance>
        {profile.status === 'not_started' ? (
          <p className="t-body-md" style={muted}>
            You have not added a profile yet. <Link to="/profile" style={{ color: 'var(--primary)' }}>Add your skills</Link> so ProjectMind can personalise
            recommendations and roadmaps.
          </p>
        ) : (
          <>
            <p className="t-body-md" style={{ color: 'var(--on-surface)' }}>
              {profile.skill_count} {profile.skill_count === 1 ? 'skill' : 'skills'} listed · profile {profile.completion_percent}% filled in
              {levels.length > 0 && ` · ${levels.map(([name, n]) => `${n} ${name}`).join(', ')}`}
            </p>
            {skills.length > 0 && (
              <ul className="mt-3 flex flex-wrap gap-2" aria-label="Declared skills">
                {skills.map((s) => (
                  <li key={s.name}>
                    <Chip>
                      {s.name} · {s.declared_level || 'no level'}
                      <span style={muted}> · {STATUS_LABEL[s.recorded_progress] || s.recorded_progress}</span>
                    </Chip>
                  </li>
                ))}
              </ul>
            )}
            {profile.status !== 'complete' && profile.missing_sections.length > 0 && (
              <p className="t-body-md mt-3" style={muted}>
                Not filled in yet: {profile.missing_sections.join(', ')}. <Link to="/profile" style={{ color: 'var(--primary)' }}>Update profile</Link>
              </p>
            )}
          </>
        )}
      </div>
    </Panel>
  )
}

function LearningSection({ learning }) {
  const t = learning.totals
  return (
    <Panel icon="checklist" title="Recorded learning progress" aria-label="Recorded learning progress" as="section">
      <div className="mt-4">
        <Provenance>Roadmap steps you marked yourself. Opening a page or generating a roadmap records nothing.</Provenance>
        {!learning.started ? (
          <div>
            <p className="t-body-md" style={{ color: 'var(--on-surface)' }}>You have not marked any roadmap steps yet.</p>
            <p className="t-body-md mt-1" style={muted}>
              Open a project, find its learning roadmap, and mark steps as in progress or completed. They will show up here.
            </p>
            <div className="mt-3">
              <LinkButton to="/search">Find a project</LinkButton>
            </div>
          </div>
        ) : (
          <>
            <p className="t-body-md" style={{ color: 'var(--on-surface)' }}>
              {t.completed} completed · {t.in_progress} in progress · {t.remaining} not started, across {learning.projects_with_progress}{' '}
              {learning.projects_with_progress === 1 ? 'roadmap' : 'roadmaps'}.
            </p>
            {learning.projects.length > 0 && (
              <ul className="mt-3 divide-y" style={{ borderColor: 'var(--border-technical)' }} aria-label="Roadmaps with progress">
                {learning.projects.map((p) => (
                  <li key={p.project_id} className="flex flex-wrap items-baseline justify-between gap-2 py-2" style={{ borderColor: 'var(--border-technical)' }}>
                    <Link to={`/project/${p.project_id}`} className="t-body-md" style={{ color: 'var(--primary)' }}>
                      {p.title}
                    </Link>
                    <span className="t-label-mono" style={{ ...muted, fontSize: 12 }}>
                      {p.completed} of {p.total_steps} completed · {p.in_progress} in progress
                    </span>
                  </li>
                ))}
              </ul>
            )}
            {learning.retired_recorded_steps > 0 && (
              <p className="t-body-md mt-2" style={{ ...muted, fontSize: 13 }}>
                {learning.retired_recorded_steps} recorded {learning.retired_recorded_steps === 1 ? 'step' : 'steps'} no longer appear in a current roadmap
                (for example after your profile changed). They are kept but not counted above.
              </p>
            )}
            {learning.projects_unavailable > 0 && (
              <p className="t-body-md mt-2" style={{ ...muted, fontSize: 13 }}>
                {learning.projects_unavailable} saved {learning.projects_unavailable === 1 ? 'roadmap' : 'roadmaps'} could not be read and{' '}
                {learning.projects_unavailable === 1 ? 'is' : 'are'} left out.
              </p>
            )}
            {learning.projects_truncated && (
              <p className="t-body-md mt-2" style={{ ...muted, fontSize: 13 }}>Showing your most recently updated roadmaps only.</p>
            )}

            {learning.skills_worked_on.length > 0 && (
              <div className="mt-4">
                <h3 className="t-label-caps" style={{ ...muted, fontSize: 11 }}>Skills you have worked on</h3>
                <ul className="mt-2 flex flex-wrap gap-2" aria-label="Skills worked on">
                  {learning.skills_worked_on.map((s) => (
                    <li key={s.skill}>
                      <Chip>
                        {s.skill} · {STATUS_LABEL[s.recorded_status]}
                        <span style={muted}> · {s.on_profile ? `profile: ${s.declared_level || 'no level'}` : 'not on profile'}</span>
                      </Chip>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {learning.recent_activity.length > 0 && (
              <div className="mt-4">
                <h3 className="t-label-caps" style={{ ...muted, fontSize: 11 }}>Most recent step updates</h3>
                <ul className="mt-2 space-y-1" aria-label="Recent step updates">
                  {learning.recent_activity.map((a) => (
                    <li key={`${a.project_id}-${a.skill}-${a.status}`} className="t-body-md" style={{ color: 'var(--on-surface)', fontSize: 13 }}>
                      {a.skill} — {STATUS_LABEL[a.status].toLowerCase()} in “{a.project_title}”{a.earlier_step ? ' (earlier step)' : ''}
                      <span style={muted}> · set {formatDate(a.status_set_at)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
      </div>
    </Panel>
  )
}

function ReviewSection({ review }) {
  if (!review.length) return null
  return (
    <Panel icon="rule" title="Worth reviewing on your profile" aria-label="Profile review" as="section">
      <div className="mt-4">
        <Provenance>ProjectMind never changes your levels. These are prompts to check whether your profile still describes you.</Provenance>
        <ul className="space-y-1" aria-label="Profile review items">
          {review.map((r) => (
            <li key={r.skill} className="t-body-md" style={{ color: 'var(--on-surface)', fontSize: 13 }}>
              <strong>{r.skill}</strong> — {r.reason}
            </li>
          ))}
        </ul>
        <div className="mt-3">
          <LinkButton to="/profile">Review profile</LinkButton>
        </div>
      </div>
    </Panel>
  )
}

function NextStepsSection({ items, learning }) {
  return (
    <Panel icon="flag" title="Suggested next steps" aria-label="Suggested next steps" as="section">
      <div className="mt-4">
        <Provenance>Suggestions from your saved roadmaps and profile. None of these is done until you mark it.</Provenance>
        {items.length === 0 ? (
          <p className="t-body-md" style={muted}>
            {learning.started ? 'Every step in your saved roadmaps is marked in progress or completed.' : 'Nothing to suggest yet. Start a project roadmap to get next steps.'}
          </p>
        ) : (
          <ul className="space-y-3" aria-label="Next steps">
            {items.map((item) =>
              item.type === 'roadmap_step' ? (
                <li key={`${item.project_id}-${item.step_id}`}>
                  <p className="t-body-md" style={{ color: 'var(--on-surface)' }}>
                    <strong>{KIND_LABEL[item.kind] || 'Step'}: {item.skill}</strong> — “{item.project_title}”
                  </p>
                  <p className="t-body-md" style={{ ...muted, fontSize: 13 }}>
                    {item.reason}{' '}
                    <Link to={item.link} style={{ color: 'var(--primary)' }}>Open roadmap</Link>
                  </p>
                </li>
              ) : (
                <li key="profile">
                  <p className="t-body-md" style={{ color: 'var(--on-surface)' }}>
                    <strong>Complete your profile</strong> — {item.reason}
                  </p>
                  <p className="t-body-md" style={{ ...muted, fontSize: 13 }}>
                    Missing: {item.missing_sections.join(', ')}. <Link to={item.link} style={{ color: 'var(--primary)' }}>Open profile</Link>
                  </p>
                </li>
              ),
            )}
          </ul>
        )}
      </div>
    </Panel>
  )
}

export default function Progress() {
  const { user, loading: authLoading } = useAuth()
  const [data, setData] = useState(null)
  const [status, setStatus] = useState('idle')
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    setStatus('loading')
    try {
      const { data: result } = await api.myInsights()
      setData(result)
      setError(null)
      setStatus('ready')
    } catch (err) {
      setError(err.message)
      setStatus('error')
    }
  }, [])

  useEffect(() => {
    if (authLoading) return
    if (!user) {
      setData(null)
      setStatus('idle')
      return
    }
    load()
  }, [user, authLoading, load])

  if (authLoading || (user && (status === 'idle' || status === 'loading'))) return <Spinner label="Loading your progress…" />

  if (!user) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-12 sm:px-6">
        <EmptyState title="Sign in to see your progress" hint="Your skills and roadmap progress are saved to your account, so we need to know who you are first.">
          <Link to="/account" className="t-label-caps mt-4 inline-block px-4 py-2" style={{ background: 'var(--primary)', color: 'var(--on-primary)', borderRadius: 8 }}>
            Sign in
          </Link>
        </EmptyState>
      </div>
    )
  }

  if (status === 'error') {
    return (
      <div className="mx-auto max-w-3xl px-4 py-12 sm:px-6">
        <ErrorNotice message={error} onRetry={load} />
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-4xl px-4 py-10 sm:px-6">
      <PageHeader
        eyebrow="Skill progress"
        title="Your skills and learning progress"
        description="What you declared, what you have recorded, and what to do next — kept separate so nothing is overstated."
      />
      <div className="space-y-6">
        <ProfileSection profile={data.profile} skills={data.profile_skills} />
        <LearningSection learning={data.learning} />
        <ReviewSection review={data.profile_review} />
        <NextStepsSection items={data.next_steps.items} learning={data.learning} />
        <p className="t-body-md" style={{ ...muted, fontSize: 12 }}>
          {data.history.note} {data.disclaimer}
        </p>
      </div>
    </div>
  )
}
