import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import api from '../services/api'
import Panel from './Panel'
import SubTeamPanel from './SubTeamPanel'
import { Spinner, ErrorNotice } from './Feedback'
import { isResourceGone } from '../utils/access'

const muted = { color: 'var(--on-surface-variant)' }
const errorStyle = { color: '#ffb4ab', fontSize: 12 }

function CreateForm({ team, onCreated }) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [module, setModule] = useState('')
  const [description, setDescription] = useState('')
  const [chosen, setChosen] = useState([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const toggle = (id) => setChosen((c) => (c.includes(id) ? c.filter((x) => x !== id) : [...c, id]))

  const submit = async (event) => {
    event.preventDefault()
    if (!name.trim()) {
      setError('Give the sub-team a name.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const { data } = await api.createSubTeam(team.team_id, { name: name.trim(), module: module.trim(), description: description.trim(), member_ids: chosen })
      onCreated(data)
      setName('')
      setModule('')
      setDescription('')
      setChosen([])
      setOpen(false)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)} className="btn-secondary t-label-caps px-3 py-2" style={{ fontSize: 10.5 }}>
        New sub-team
      </button>
    )
  }

  return (
    <form onSubmit={submit} className="space-y-2 p-3" style={{ border: '1px solid var(--border-technical)', borderRadius: 8 }} aria-label="Create sub-team">
      <input value={name} onChange={(e) => setName(e.target.value)} maxLength={80} placeholder="Sub-team name, e.g. Backend API" aria-label="Sub-team name" className="gm-input w-full px-3 py-2 text-sm" />
      <input value={module} onChange={(e) => setModule(e.target.value)} maxLength={80} placeholder="Module or workstream (optional)" aria-label="Module" className="gm-input w-full px-3 py-2 text-sm" />
      <textarea value={description} onChange={(e) => setDescription(e.target.value)} maxLength={500} rows={2} placeholder="What will this sub-team build? (optional)" aria-label="Description" className="gm-input w-full px-3 py-2 text-sm" />
      <fieldset>
        <legend className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>Members (from this team)</legend>
        <div className="mt-1 flex flex-wrap gap-3">
          {team.members.map((m) => (
            <label key={m.user_id} className="t-body-md flex items-center gap-1.5" style={{ fontSize: 13 }}>
              <input type="checkbox" checked={chosen.includes(m.user_id)} onChange={() => toggle(m.user_id)} />
              {m.name}
            </label>
          ))}
        </div>
      </fieldset>
      {error && <p role="alert" style={errorStyle}>{error}</p>}
      <div className="flex gap-2">
        <button type="submit" disabled={busy} className="btn-primary t-label-caps px-3 py-1.5" style={{ fontSize: 10 }}>
          {busy ? 'Creating…' : 'Create sub-team'}
        </button>
        <button type="button" onClick={() => setOpen(false)} className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>
          Cancel
        </button>
      </div>
    </form>
  )
}

function JoinByCode({ onJoined }) {
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const submit = async (event) => {
    event.preventDefault()
    if (!code.trim()) return
    setBusy(true)
    setError(null)
    try {
      const { data } = await api.joinSubTeam(code.trim())
      onJoined(data)
      setCode('')
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-wrap items-center gap-2" aria-label="Join a sub-team with a code">
      <input
        value={code}
        onChange={(e) => setCode(e.target.value.toUpperCase())}
        placeholder="Sub-team invite code"
        aria-label="Sub-team invite code"
        maxLength={32}
        className="gm-input w-48 px-3 py-2 text-sm uppercase tracking-wider"
      />
      <button type="submit" disabled={busy || !code.trim()} className="btn-secondary t-label-caps px-3 py-2" style={{ fontSize: 10.5 }}>
        Join sub-team
      </button>
      {error && <p role="alert" style={errorStyle}>{error}</p>}
    </form>
  )
}

function SubTeamCard({ sub, selected, onOpen }) {
  const canOpen = sub.is_member || sub.can_manage
  return (
    <li className="p-3" style={{ border: `1px solid ${selected ? 'var(--primary)' : 'var(--border-technical)'}`, borderRadius: 8 }}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="t-label-mono" style={{ color: 'var(--primary)', fontSize: 14 }}>{sub.name}</p>
          {sub.module && <p className="t-label-mono" style={{ color: 'var(--outline)', fontSize: 11 }}>{sub.module}</p>}
        </div>
        <div className="flex flex-wrap gap-1.5">
          {sub.is_member && <span className="gm-chip px-2 py-0.5">You’re in</span>}
          {sub.status === 'archived' && <span className="gm-chip px-2 py-0.5">Archived</span>}
          <span className="t-label-mono" style={{ color: 'var(--outline)', fontSize: 11 }}>
            {sub.member_count} {sub.member_count === 1 ? 'member' : 'members'}
          </span>
        </div>
      </div>
      {sub.description && <p className="t-body-md mt-1" style={{ ...muted, fontSize: 12.5 }}>{sub.description}</p>}
      <div className="mt-2">
        {canOpen ? (
          <button type="button" onClick={() => onOpen(sub.sub_team_id)} aria-label={`Open ${sub.name}`} className="t-label-caps" style={{ color: 'var(--primary)', fontSize: 10.5 }}>
            Open
          </button>
        ) : (
          <span className="t-label-mono" style={{ color: 'var(--outline)', fontSize: 11 }}>Members only — ask the team owner to add you.</span>
        )}
      </div>
    </li>
  )
}

/**
 * Sub-teams inside a parent TeamRoom. Fully self-contained: if loading them fails
 * the rest of the room is unaffected and this section offers its own retry.
 * Showing or hiding a control here is convenience only - the server authorises
 * every action against the parent team's current roster.
 */
export default function SubTeams({ team, user }) {
  const isOwner = team.owner_user_id === user.user_id
  const [subs, setSubs] = useState([])
  const [status, setStatus] = useState('loading')
  const [error, setError] = useState(null)
  const [selected, setSelected] = useState(null)
  const [endedStatus, setEndedStatus] = useState(null)

  // The reliable roster-change signal: the SET of parent-team member ids. TeamRoom replaces its
  // `team` object on every rename, skills save or member removal, so the object itself changes
  // too often to key on; the sorted ids change only when someone joins or leaves the team.
  const rosterKey = useMemo(
    () => (team.members || []).map((m) => m.user_id).sort().join('|'),
    [team.members],
  )

  const load = useCallback(async () => {
    setStatus('loading')
    try {
      const res = await api.listSubTeams(team.team_id)
      setSubs(res.data)
      setStatus('done')
    } catch (err) {
      setError(err.message)
      setStatus('error')
    }
  }, [team.team_id])

  useEffect(() => {
    load()
  }, [load])

  // Re-reads the list WITHOUT the loading state, so it does not flash or close an open panel.
  // If the whole section has become unreachable (removed from the team, session gone) the list
  // and panel are dropped; any other failure (network, 5xx) keeps what is already shown.
  const refresh = useCallback(async () => {
    try {
      const res = await api.listSubTeams(team.team_id)
      setSubs(res.data)
      setStatus('done')
      setEndedStatus(null)
    } catch (err) {
      if (isResourceGone(err)) {
        setEndedStatus(err.status)
        setSelected(null)
        setSubs([])
      }
    }
  }, [team.team_id])

  const lastRoster = useRef(rosterKey)
  useEffect(() => {
    if (lastRoster.current === rosterKey) return
    lastRoster.current = rosterKey
    refresh()
  }, [rosterKey, refresh])

  const upsert = (sub) =>
    setSubs((list) => {
      const exists = list.some((s) => s.sub_team_id === sub.sub_team_id)
      return exists ? list.map((s) => (s.sub_team_id === sub.sub_team_id ? { ...s, ...sub } : s)) : [...list, sub]
    })

  return (
    <Panel
      icon="account_tree"
      title="Sub-teams"
      description="Smaller groups from this team working on one module. Each has its own chat, roles and tasks."
      as="section"
      aria-label="Sub-teams"
    >
      <div className="mt-4 space-y-4">
        {endedStatus ? (
          <p className="t-body-md" role="alert" style={muted}>
            {endedStatus === 401
              ? 'Your session has ended. Sign in again to see this team’s sub-teams.'
              : 'You no longer have access to this team’s sub-teams. You may have been removed from the team.'}
          </p>
        ) : (
          <>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <JoinByCode onJoined={(sub) => { upsert(sub); setSelected(sub.sub_team_id) }} />
              {isOwner && <CreateForm team={team} onCreated={(sub) => { upsert(sub); setSelected(sub.sub_team_id) }} />}
            </div>

            {status === 'loading' && <Spinner label="Loading sub-teams…" />}
            {status === 'error' && <ErrorNotice message={error} onRetry={load} />}
            {status === 'done' && subs.length === 0 && (
              <p className="t-body-md" style={muted}>
                {isOwner ? 'No sub-teams yet. Create one to split the project into modules.' : 'This team has no sub-teams yet. The team owner creates them.'}
              </p>
            )}
            {status === 'done' && subs.length > 0 && (
              <ul className="grid gap-3 md:grid-cols-2" aria-label="Sub-teams list">
                {subs.map((s) => (
                  <SubTeamCard key={s.sub_team_id} sub={s} selected={selected === s.sub_team_id} onOpen={setSelected} />
                ))}
              </ul>
            )}

            {selected && (
              <SubTeamPanel
                key={selected}
                team={team}
                user={user}
                subId={selected}
                onClose={() => setSelected(null)}
                rosterKey={rosterKey}
                onChanged={upsert}
                onAccessLost={refresh}
                onDeleted={(id) => {
                  setSubs((list) => list.filter((s) => s.sub_team_id !== id))
                  setSelected(null)
                }}
              />
            )}
          </>
        )}
      </div>
    </Panel>
  )
}
