import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import useAuth from '../hooks/useAuth.jsx'
import api from '../services/api'
import Panel from './Panel'
import { Spinner, ErrorNotice } from './Feedback'

const muted = { color: 'var(--on-surface-variant)' }
const SOURCE_LABEL = {
  profile: 'Saved profile',
  'profile+manual': 'Profile + team skills',
  manual: 'Typed-in skills',
  none: 'No skills on file',
}
const SIZES = [1, 2, 3, 4, 5, 6, 7, 8]
const emptyRow = () => ({ name: '', skills: '' })

function Contribution({ c }) {
  return (
    <span
      className="t-label-mono px-2 py-0.5"
      style={{
        fontSize: 11,
        borderRadius: 999,
        border: `1px ${c.strength === 'solid' ? 'solid' : 'dashed'} var(--border-technical)`,
        color: 'var(--on-surface)',
      }}
      title={c.strength === 'solid' ? 'Solid evidence (self-reported)' : 'Partial: used before or rated below this project’s bar'}
    >
      {c.skill}
      {c.level ? ` · ${c.level.toLowerCase()}` : ''}
      {c.strength === 'partial' ? ' · partial' : ''}
    </span>
  )
}

function TeamView({ team }) {
  const { requirements: req, roles, bottlenecks } = team
  const uncovered = req.items.filter((i) => i.status === 'uncovered')
  const partial = req.items.filter((i) => i.status === 'partial')
  return (
    <div>
      {!team.recommended && (
        <p className="t-body-md p-2" style={{ background: 'var(--surface-container-low)', borderRadius: 8, ...muted, fontSize: 12 }}>
          For comparison only — not a recommendation.
        </p>
      )}
      <p className="t-body-md mt-2" style={{ color: 'var(--on-surface)', fontSize: 13 }}>{team.explanation}</p>

      <ul className="mt-3 space-y-2" aria-label="Team members">
        {team.members.map((m) => (
          <li key={m.name} className="p-3" style={{ border: '1px solid var(--border-technical)', borderRadius: 8 }}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="t-label-mono" style={{ color: 'var(--on-surface)' }}>{m.name}</p>
              <span className="gm-chip px-2 py-0.5" style={{ fontSize: 10 }}>{SOURCE_LABEL[m.source]}</span>
            </div>
            {m.suggested_role && (
              <p className="t-body-md mt-1" style={{ ...muted, fontSize: 12 }}>
                Best-fit role: {m.suggested_role.role} ({m.suggested_role.confidence})
              </p>
            )}
            {m.contributes.length > 0 ? (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {m.contributes.map((c) => <Contribution key={c.skill} c={c} />)}
              </div>
            ) : (
              <p className="t-body-md mt-2" style={{ ...muted, fontSize: 12 }}>No project requirement is covered by the skills on file.</p>
            )}
            {m.sole_holder_of.length > 0 && (
              <p className="t-body-md mt-2" style={{ ...muted, fontSize: 12 }}>Only person here with solid evidence for: {m.sole_holder_of.join(', ')}.</p>
            )}
            {m.profile_status && m.profile_status !== 'complete' && (
              <p className="t-body-md mt-1" style={{ color: 'var(--outline)', fontSize: 11.5 }}>
                Profile {m.profile_status === 'not_started' ? 'not started' : 'incomplete'} — their skills may be under-counted.
              </p>
            )}
          </li>
        ))}
      </ul>

      <section className="mt-4" aria-label="Requirement coverage">
        <p className="t-label-mono" style={{ color: 'var(--on-surface)', fontSize: 12.5 }}>
          {req.solid} of {req.total} requirements solid · {req.partial} partial · {req.uncovered} not covered
        </p>
        {partial.length > 0 && <p className="t-body-md mt-1" style={{ ...muted, fontSize: 12 }}>Partial: {partial.map((i) => i.skill).join(', ')}</p>}
        {uncovered.length > 0 && <p className="t-body-md mt-1" style={{ color: '#e3ab6a', fontSize: 12 }}>Not covered: {uncovered.map((i) => i.skill).join(', ')}</p>}
      </section>

      <section className="mt-3" aria-label="Role coverage">
        {roles.covered.filter((c) => c.priority).map((c) => (
          <p key={c.role} className="t-body-md" style={{ ...muted, fontSize: 12 }}>
            <span style={{ color: '#7bcf9f' }}>Covered</span> · {c.role}: {c.primary.join(', ')}
          </p>
        ))}
        {roles.gaps.map((g) => (
          <p key={g.role} className="t-body-md" style={{ ...muted, fontSize: 12 }}>
            <span style={{ color: '#e3ab6a' }}>No owner</span> · {g.role}. {g.note}
          </p>
        ))}
        {roles.overlaps.map((o) => (
          <p key={o.role} className="t-body-md" style={{ ...muted, fontSize: 12 }}>
            <span style={{ color: '#e3ab6a' }}>Overlap</span> · {o.note}
          </p>
        ))}
      </section>

      {bottlenecks.length > 0 && (
        <section className="mt-3" aria-label="Single-person dependencies">
          {bottlenecks.map((b) => (
            <p key={b.member} className="t-body-md" style={{ color: '#e3ab6a', fontSize: 12 }}>
              Dependency · {b.note} ({b.requirements.join(', ')})
            </p>
          ))}
        </section>
      )}
    </div>
  )
}

/**
 * Smart team formation (POST /api/teams/formation). Strictly advisory: the
 * request only computes; it never invites anyone, creates a team or changes
 * membership, and the panel says so. The candidate pool is limited to what the
 * server authorises - you, a team you belong to, and people you type in.
 */
export default function TeamFormation({ projectId }) {
  const { user, loading: authLoading } = useAuth()
  const [teams, setTeams] = useState([])
  const [teamId, setTeamId] = useState('')
  const [includeSelf, setIncludeSelf] = useState(true)
  const [size, setSize] = useState('')
  const [rows, setRows] = useState([])
  const [status, setStatus] = useState('idle') // idle | loading | done | error
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [selected, setSelected] = useState('best_coverage')
  const requestId = useRef(0)

  useEffect(() => {
    if (authLoading || !user) return
    api.myTeams().then((res) => setTeams(res.data ?? [])).catch(() => setTeams([]))
  }, [authLoading, user])

  if (authLoading) return null

  if (!user) {
    return (
      <Panel icon="diversity_3" title="Form a balanced team" description="Find the combination of people whose skills cover this project." compact>
        <p className="t-body-md" style={{ ...muted, fontSize: 13 }}>
          <Link to="/account" className="underline" style={{ color: 'var(--primary)' }}>Sign in</Link> to compare yourself, a team you belong to, or people you add.
        </p>
      </Panel>
    )
  }

  const run = async (event) => {
    event.preventDefault()
    if (status === 'loading') return
    const candidates = rows
      .map((r) => ({ name: r.name.trim(), skills: r.skills.split(',').map((s) => s.trim()).filter(Boolean) }))
      .filter((r) => r.name)
    if (!includeSelf && !teamId && candidates.length === 0) {
      setError('Choose at least one candidate: include yourself, pick a team, or add someone.')
      setStatus('error')
      return
    }
    const id = ++requestId.current
    setStatus('loading')
    setError(null)
    try {
      const { data } = await api.formTeams({
        project_id: projectId,
        include_self: includeSelf,
        ...(teamId ? { team_id: teamId } : {}),
        ...(size ? { team_size: Number(size) } : {}),
        candidates,
      })
      if (id !== requestId.current) return
      setResult(data)
      setSelected(data.teams[0]?.key ?? 'best_coverage')
      setStatus('done')
    } catch (err) {
      if (id !== requestId.current) return
      setError(err.message)
      setStatus('error')
    }
  }

  const updateRow = (i, patch) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  const team = result?.teams.find((t) => t.key === selected) ?? result?.teams[0]

  return (
    <Panel icon="diversity_3" title="Form a balanced team" description="Compare combinations of people by how well their skills cover this project. Advice only." compact>
      <form onSubmit={run} className="space-y-3">
        <div className="flex flex-wrap items-end gap-3">
          <label className="block">
            <span className="t-label-caps block" style={{ color: 'var(--outline)', fontSize: 10 }}>Use a team I’m in</span>
            <select value={teamId} onChange={(e) => setTeamId(e.target.value)} className="gm-input mt-1 px-2 py-2 text-sm">
              <option value="">No team</option>
              {teams.map((t) => <option key={t.team_id} value={t.team_id}>{t.name}</option>)}
            </select>
          </label>
          <label className="block">
            <span className="t-label-caps block" style={{ color: 'var(--outline)', fontSize: 10 }}>Team size</span>
            <select value={size} onChange={(e) => setSize(e.target.value)} className="gm-input mt-1 px-2 py-2 text-sm">
              <option value="">Automatic</option>
              {SIZES.map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
          <label className="flex items-center gap-2" style={{ color: 'var(--on-surface)', fontSize: 13 }}>
            <input type="checkbox" checked={includeSelf} onChange={(e) => setIncludeSelf(e.target.checked)} />
            Include me
          </label>
        </div>

        <div>
          <p className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>People you might invite (optional)</p>
          <p className="t-body-md mt-1" style={{ ...muted, fontSize: 12 }}>
            Type a name and what they can do. They are not looked up, contacted or stored.
          </p>
          {rows.map((r, i) => (
            <div key={i} className="mt-2 flex flex-wrap gap-2">
              <input aria-label={`Person ${i + 1} name`} value={r.name} onChange={(e) => updateRow(i, { name: e.target.value })} maxLength={60} placeholder="Name" className="gm-input w-40 px-3 py-2 text-sm" />
              <input aria-label={`Person ${i + 1} skills`} value={r.skills} onChange={(e) => updateRow(i, { skills: e.target.value })} placeholder="Skills, comma separated" className="gm-input min-w-0 flex-1 px-3 py-2 text-sm" />
              <button type="button" aria-label={`Remove person ${i + 1}`} onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))} className="t-label-caps px-2" style={{ color: 'var(--outline)', fontSize: 10 }}>Remove</button>
            </div>
          ))}
          <button type="button" disabled={rows.length >= 12} onClick={() => setRows((rs) => [...rs, emptyRow()])} className="t-label-caps mt-2 px-3 py-1.5" style={{ border: '1px solid var(--border-technical)', borderRadius: 8, color: 'var(--on-surface)', fontSize: 10.5 }}>
            Add a person
          </button>
        </div>

        <button type="submit" disabled={status === 'loading'} className="btn-primary t-label-caps px-4 py-2">
          {status === 'loading' ? 'Comparing…' : 'Suggest teams'}
        </button>
      </form>

      {status === 'loading' && <Spinner label="Comparing combinations…" />}
      {status === 'error' && <div className="mt-3"><ErrorNotice message={error} onRetry={() => run({ preventDefault() {} })} /></div>}

      {status === 'done' && result && (
        <div className="mt-5">
          {result.notes.map((n) => <p key={n} className="t-body-md mt-1" style={{ ...muted, fontSize: 12.5 }}>{n}</p>)}
          {result.requirements.total === 0 && (
            <p className="t-body-md mt-2" style={{ ...muted, fontSize: 13 }}>This project lists no requirements, so there is nothing to build a team around.</p>
          )}
          {result.requirements.limited && result.requirements.total > 0 && (
            <p className="t-body-md mt-1" style={{ ...muted, fontSize: 12.5 }}>This project lists very few requirements, so the suggestion is only loosely project-specific.</p>
          )}
          {result.pool.not_matched.length > 0 && (
            <p className="t-body-md mt-1" style={{ ...muted, fontSize: 12.5 }}>
              Not matched: {result.pool.not_matched.map((p) => p.name).join(', ')} — no skills on file. That does not mean they lack skills.
            </p>
          )}

          {result.teams.length === 0 ? (
            result.requirements.total > 0 && <p className="t-body-md mt-3" style={{ ...muted, fontSize: 13 }}>No team can be suggested from this pool yet.</p>
          ) : (
            <>
              <div role="radiogroup" aria-label="Suggested teams" className="mt-3 flex flex-wrap gap-2">
                {result.teams.map((t) => (
                  <button
                    key={t.key}
                    type="button"
                    role="radio"
                    aria-checked={t.key === (team?.key)}
                    onClick={() => setSelected(t.key)}
                    className="t-label-mono px-3 py-1.5 transition hover:opacity-85"
                    style={{
                      fontSize: 11.5,
                      borderRadius: 999,
                      border: `1px solid ${t.key === team?.key ? 'var(--primary)' : 'var(--border-technical)'}`,
                      background: t.key === team?.key ? 'var(--primary)' : 'transparent',
                      color: t.key === team?.key ? 'var(--on-primary)' : 'var(--on-surface-variant)',
                    }}
                  >
                    {t.label}
                  </button>
                ))}
              </div>
              {team && <TeamView team={team} />}

              <div className="mt-5 p-3" style={{ background: 'var(--surface-container-low)', borderRadius: 8 }}>
                <p className="t-label-mono" style={{ color: 'var(--on-surface)', fontSize: 12 }}>Nothing has been created, invited or changed.</p>
                <p className="t-body-md mt-1" style={{ ...muted, fontSize: 12 }}>
                  To go ahead, {teamId ? <Link to={`/teams/${teamId}`} className="underline" style={{ color: 'var(--primary)' }}>open your team</Link> : <a href="#start-team" className="underline" style={{ color: 'var(--primary)' }}>start a team workspace below</a>} and share its invite code yourself.
                </p>
              </div>
            </>
          )}

          <details className="mt-4">
            <summary className="t-label-caps cursor-pointer" style={{ color: 'var(--outline)', fontSize: 10 }}>How teams are chosen, and what this assumes</summary>
            <p className="t-body-md mt-2" style={{ ...muted, fontSize: 12 }}>{result.objective}</p>
            {result.inputs?.default_rule && <p className="t-body-md mt-1" style={{ ...muted, fontSize: 12 }}>{result.inputs.default_rule}</p>}
            <ul className="mt-2 list-disc pl-5" style={{ ...muted, fontSize: 12 }}>
              {result.limitations.map((l) => <li key={l}>{l}</li>)}
            </ul>
          </details>
        </div>
      )}
    </Panel>
  )
}
