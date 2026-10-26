import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import api from '../services/api'

const SOURCE_LABEL = {
  profile: 'From saved profile',
  'profile+manual': 'From profile + team skills',
  manual: 'From skills entered for this team',
  none: 'No skills on file',
}

const muted = { color: 'var(--on-surface-variant)' }

function SourceBadge({ source }) {
  return (
    <span className="gm-chip px-2 py-0.5" style={{ fontSize: 10 }} title="Where this person's skills came from">
      {SOURCE_LABEL[source] ?? source}
    </span>
  )
}

function Skills({ skills }) {
  return (
    <p className="t-body-md mt-1" style={{ ...muted, fontSize: 12 }}>
      Supported by:{' '}
      {skills.map((s, i) => (
        <span key={s.name}>
          {i > 0 && ', '}
          <span style={{ color: 'var(--on-surface)' }}>{s.name}</span>
          {s.level && <span> ({s.level.toLowerCase()}, self-reported)</span>}
        </span>
      ))}
    </p>
  )
}

function DecisionLine({ decision }) {
  if (!decision) return null
  const text =
    decision.status === 'rejected'
      ? 'Declined this suggestion'
      : decision.status === 'custom'
        ? `Chose ${decision.role} instead`
        : `Confirmed as ${decision.role}`
  return (
    <p className="t-label-mono mt-2" style={{ color: decision.status === 'rejected' ? 'var(--outline)' : '#7bcf9f', fontSize: 11 }}>
      {text}
    </p>
  )
}

function MemberCard({ member, isSelf, decision, roles, teamId, onDecisions }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [choosing, setChoosing] = useState(false)
  const [custom, setCustom] = useState('')
  const top = member.suggested

  const send = async (payload) => {
    setBusy(true)
    setError(null)
    try {
      const { data } = await api.setMyRoleDecision(teamId, payload)
      onDecisions(data)
      setChoosing(false)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }
  const clear = async () => {
    setBusy(true)
    setError(null)
    try {
      const { data } = await api.clearMyRoleDecision(teamId)
      onDecisions(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <li className="p-3" style={{ border: '1px solid var(--border-technical)', borderRadius: 8 }}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="t-label-mono" style={{ color: 'var(--on-surface)' }}>
          {member.name}
          {isSelf && <span style={{ color: 'var(--outline)' }}> (you)</span>}
        </p>
        <SourceBadge source={member.source} />
      </div>

      {top ? (
        <>
          <p className="t-body-md mt-2" style={{ color: 'var(--on-surface)' }}>
            <span className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 9.5 }}>Suggested </span>
            {top.role}
            <span
              className="t-label-mono ml-2"
              style={{ color: 'var(--primary)', fontSize: 11.5 }}
              title="A heuristic of the self-reported evidence for this role, 0–100. Not a probability and not verified ability."
            >
              {top.confidence} · {Math.round(top.score)}/100
            </span>
          </p>
          <Skills skills={top.supporting_skills} />
          <p className="t-body-md mt-1" style={{ ...muted, fontSize: 12 }}>{top.explanation}</p>
          {top.missing_skills.length > 0 && (
            <p className="t-body-md mt-1" style={{ ...muted, fontSize: 12 }}>Project needs they haven’t listed: {top.missing_skills.join(', ')}.</p>
          )}
          {member.alternatives.length > 0 && (
            <p className="t-body-md mt-1" style={{ ...muted, fontSize: 12 }}>
              Could also fit: {member.alternatives.map((a) => `${a.role} (${Math.round(a.score)})`).join(', ')}.
            </p>
          )}
        </>
      ) : (
        <p className="t-body-md mt-2" style={{ ...muted, fontSize: 12.5 }}>{member.message}</p>
      )}

      <DecisionLine decision={decision} />

      {isSelf && (
        <div className="mt-2">
          {top && !decision && (
            <div className="flex flex-wrap gap-2">
              <button type="button" disabled={busy} onClick={() => send({ status: 'accepted', role: top.role })} className="btn-primary t-label-caps px-3 py-1" style={{ fontSize: 10 }}>
                Accept
              </button>
              <button type="button" disabled={busy} onClick={() => send({ status: 'rejected', role: top.role })} className="t-label-caps px-3 py-1" style={{ border: '1px solid var(--border-technical)', borderRadius: 6, fontSize: 10, color: 'var(--on-surface)' }}>
                Decline
              </button>
            </div>
          )}
          {!choosing && (
            <button type="button" onClick={() => setChoosing(true)} className="t-label-caps mt-2" style={{ color: 'var(--outline)', fontSize: 10 }}>
              Choose a different role
            </button>
          )}
          {choosing && (
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <select aria-label="Choose your role" value={custom} onChange={(e) => setCustom(e.target.value)} className="gm-input px-2 py-1 text-xs">
                <option value="">Select a role…</option>
                {roles.map((r) => (
                  <option key={r}>{r}</option>
                ))}
              </select>
              <button type="button" disabled={busy || !custom} onClick={() => send({ status: 'custom', role: custom })} className="btn-primary t-label-caps px-3 py-1" style={{ fontSize: 10 }}>
                Confirm role
              </button>
              <button type="button" onClick={() => setChoosing(false)} className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>
                Cancel
              </button>
            </div>
          )}
          {decision && (
            <button type="button" disabled={busy} onClick={clear} className="t-label-caps mt-2 block" style={{ color: 'var(--outline)', fontSize: 10 }}>
              Undo my decision
            </button>
          )}
          {(member.profile_status !== 'complete' || member.source === 'none') && (
            <p className="t-body-md mt-2" style={{ ...muted, fontSize: 12 }}>
              {member.source === 'manual' || member.source === 'none' ? 'Suggestions use only the skills you typed for this team. ' : 'Your profile is incomplete. '}
              <Link to="/profile?setup=1" className="underline" style={{ color: 'var(--primary)' }}>
                {member.profile_status === 'not_started' ? 'Add your profile' : 'Complete your profile'}
              </Link>
              {' '}for better suggestions.
            </p>
          )}
          {member.profile_shared === false && (
            <p className="t-body-md mt-2" style={{ ...muted, fontSize: 12 }}>
              Teammates can’t see your profile skills, so they only see what you typed for this team.{' '}
              <Link to="/profile" className="underline" style={{ color: 'var(--primary)' }}>Change sharing</Link>
            </p>
          )}
          {error && <p role="alert" className="t-body-md mt-2" style={{ color: '#ffb4ab', fontSize: 12 }}>{error}</p>}
        </div>
      )}
    </li>
  )
}

function Coverage({ team }) {
  const priority = team.needed_roles.filter((n) => n.priority)
  if (!priority.length && !team.plan.length) return null
  const changed = team.plan.filter((p) => p.differs)
  return (
    <div className="mt-4 space-y-2" aria-label="Team coverage">
      <p className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>Team coverage · advisory</p>
      {team.covered.filter((c) => c.priority).map((c) => (
        <p key={c.role} className="t-body-md" style={{ ...muted, fontSize: 12.5 }}>
          <span style={{ color: '#7bcf9f' }}>Covered</span> · {c.role}: {c.primary.join(', ')}
        </p>
      ))}
      {team.gaps.map((g) => (
        <p key={g.role} className="t-body-md" style={{ ...muted, fontSize: 12.5 }}>
          <span style={{ color: '#e3ab6a' }}>No owner</span> · {g.role}. {g.note}
        </p>
      ))}
      {team.overlaps.map((o) => (
        <p key={o.role} className="t-body-md" style={{ ...muted, fontSize: 12.5 }}>
          <span style={{ color: '#e3ab6a' }}>Overlap</span> · {o.note}
        </p>
      ))}
      {team.optional_roles.length > 0 && (
        <p className="t-body-md" style={{ ...muted, fontSize: 12 }}>
          Also useful if the team has capacity: {team.optional_roles.join(', ')}.
        </p>
      )}
      {changed.length > 0 && (
        <div className="p-3" style={{ background: 'var(--surface-container-low)', borderRadius: 8 }}>
          <p className="t-label-mono" style={{ color: 'var(--on-surface)', fontSize: 12 }}>A more balanced split</p>
          <ul className="mt-1 space-y-0.5">
            {changed.map((p) => (
              <li key={p.member} className="t-body-md" style={{ ...muted, fontSize: 12 }}>
                {p.member}: {p.role} instead of {p.individual_role}
              </li>
            ))}
          </ul>
          <p className="t-body-md mt-1" style={{ ...muted, fontSize: 11.5 }}>Nobody is assigned automatically — each person decides for themselves.</p>
        </div>
      )}
    </div>
  )
}

/**
 * Job-role suggestions for a team (GET /teams/<id>/roles → role_fit), clearly
 * separated from confirmed roles: a suggestion is advice until the member it
 * is about accepts it, declines it or picks another role themselves.
 */
export default function RoleFitPanel({ result, userId, teamId }) {
  const [roles, setRoles] = useState([])
  const [decisions, setDecisions] = useState(result.decisions ?? [])
  const fit = result.role_fit

  useEffect(() => setDecisions(result.decisions ?? []), [result])
  useEffect(() => {
    api.learnerProfileOptions().then((res) => setRoles(res.data.team_roles)).catch(() => setRoles([]))
  }, [])

  if (!fit) return null
  const decisionFor = (id) => decisions.find((d) => d.user_id === id)

  return (
    <div>
      <p className="t-body-md" style={{ ...muted, fontSize: 12 }} title={fit.score_meaning}>
        Suggestions are advice based on self-reported skills — they are not assignments.
      </p>
      <ul className="mt-3 space-y-2">
        {fit.members.map((m) => (
          <MemberCard
            key={m.user_id}
            member={m}
            isSelf={m.user_id === userId}
            decision={decisionFor(m.user_id)}
            roles={roles}
            teamId={teamId}
            onDecisions={setDecisions}
          />
        ))}
      </ul>
      {!fit.has_project_requirements && (
        <p className="t-body-md mt-3" style={{ ...muted, fontSize: 12 }}>This project lists no technologies or skills, so suggestions rest on each person’s skills alone.</p>
      )}
      <Coverage team={fit.team} />
    </div>
  )
}
