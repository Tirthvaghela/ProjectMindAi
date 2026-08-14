import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import useAuth from '../hooks/useAuth.jsx'
import api from '../services/api'
import PageHeader from '../components/PageHeader'
import { Spinner, ErrorNotice, EmptyState } from '../components/Feedback'

function TeamAccessPanel({ onJoined }) {
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const join = async (event) => {
    event.preventDefault()
    if (!code.trim()) return
    setBusy(true)
    setError(null)
    try {
      const { data } = await api.joinTeam(code.trim())
      onJoined(data)
      setCode('')
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="glass-panel w-full max-w-xs shrink-0 p-4" style={{ borderRadius: 8 }}>
      <span className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>
        Team access
      </span>
      <form onSubmit={join} className="mt-2 flex gap-2">
        <input
          value={code}
          onChange={(e) => setCode(e.target.value.toUpperCase())}
          placeholder="Invite code"
          aria-label="Invite code"
          className="gm-input min-w-0 flex-1 px-3 py-2 text-sm uppercase tracking-wider"
        />
        <button
          type="submit"
          disabled={busy}
          aria-label="Join team"
          className="grid h-9 w-9 shrink-0 place-items-center transition hover:opacity-85 disabled:opacity-50"
          style={{ background: 'var(--primary)', color: 'var(--on-primary)', borderRadius: 6 }}
        >
          <span className="material-symbols-outlined" style={{ fontSize: 18 }}>
            arrow_forward
          </span>
        </button>
      </form>
      {error && (
        <p className="t-body-md mt-2" style={{ color: '#ffb4ab', fontSize: 12 }}>
          {error}
        </p>
      )}
      <Link
        to="/dashboard"
        title="Start one from a project's page"
        className="t-label-caps mt-3 flex w-full items-center justify-center gap-2 px-4 py-2.5 transition hover:opacity-85"
        style={{ background: 'var(--primary)', color: 'var(--on-primary)', borderRadius: 8 }}
      >
        <span className="material-symbols-outlined" style={{ fontSize: 16 }}>
          add
        </span>
        New team
      </Link>
    </div>
  )
}

function TeamTile({ team, featured }) {
  return (
    <Link
      to={`/teams/${team.team_id}`}
      className={`glass-panel card-hover flex flex-col p-5 transition ${featured ? 'md:col-span-2' : ''}`}
      style={{ borderRadius: 8 }}
    >
      <div className="flex items-start justify-between gap-3">
        <h3
          className={featured ? 't-headline-md' : 't-label-mono'}
          style={{ color: 'var(--primary)', fontSize: featured ? undefined : 15 }}
        >
          {team.name}
        </h3>
        <span className="t-label-mono flex shrink-0 items-center gap-1" style={{ color: 'var(--outline)', fontSize: 12 }}>
          <span className="material-symbols-outlined" style={{ fontSize: 15 }}>
            group
          </span>
          {team.members.length}
        </span>
      </div>
      {team.invite_code && (
        <p className="t-label-mono mt-1" style={{ color: 'var(--outline)', fontSize: 11 }}>
          INVITE {team.invite_code}
        </p>
      )}
      <p className="t-body-md mt-3 flex-1" style={{ color: 'var(--on-surface-variant)', fontSize: featured ? 14 : 13 }}>
        {team.project_title}
      </p>
      <div className="mt-4 flex items-center justify-between gap-3 pt-3" style={{ borderTop: '1px solid var(--border-technical)' }}>
        {team.domain ? <span className="gm-chip px-2 py-0.5">{team.domain}</span> : <span />}
        <span className="t-label-caps flex items-center gap-1" style={{ color: 'var(--primary)', fontSize: 11 }}>
          Open team
          <span className="material-symbols-outlined" style={{ fontSize: 14 }}>
            arrow_forward
          </span>
        </span>
      </div>
    </Link>
  )
}

/** Domain breakdown across all of a member's teams — only worth a panel
 * once there's more than one domain to actually compare. */
function DomainDistribution({ teams }) {
  const counts = useMemo(() => {
    const map = new Map()
    teams.forEach((t) => {
      const key = t.domain || 'Other'
      map.set(key, (map.get(key) || 0) + 1)
    })
    return [...map.entries()].sort((a, b) => b[1] - a[1])
  }, [teams])

  if (counts.length < 2) return null
  const max = Math.max(...counts.map(([, n]) => n))

  return (
    <div className="glass-panel p-5" style={{ borderRadius: 8 }}>
      <span className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>
        Team distribution
      </span>
      <div className="mt-3 space-y-2.5">
        {counts.map(([domain, count]) => (
          <div key={domain} className="flex items-center gap-3">
            <span className="t-label-mono w-28 shrink-0 truncate" style={{ color: 'var(--on-surface-variant)', fontSize: 12 }}>
              {domain}
            </span>
            <div className="h-2 flex-1 overflow-hidden rounded-full" style={{ background: 'var(--surface-container-high)' }}>
              <div className="h-full rounded-full" style={{ background: 'var(--primary)', width: `${(count / max) * 100}%` }} />
            </div>
            <span className="t-label-mono w-4 shrink-0 text-right tabular-nums" style={{ color: 'var(--on-surface)', fontSize: 12 }}>
              {count}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function Teams() {
  const { user, loading: authLoading } = useAuth()
  const [teams, setTeams] = useState([])
  const [status, setStatus] = useState('loading')
  const [error, setError] = useState(null)
  const [domainFilter, setDomainFilter] = useState('all')
  const [query, setQuery] = useState('')

  const load = () => {
    setStatus('loading')
    api
      .myTeams()
      .then((res) => {
        setTeams(res.data)
        setStatus('done')
      })
      .catch((err) => {
        setError(err.message)
        setStatus('error')
      })
  }

  useEffect(() => {
    if (user) load()
  }, [user])

  const domains = useMemo(() => [...new Set(teams.map((t) => t.domain).filter(Boolean))].sort(), [teams])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return teams.filter((t) => {
      if (domainFilter !== 'all' && t.domain !== domainFilter) return false
      if (q) return t.name.toLowerCase().includes(q) || t.project_title.toLowerCase().includes(q)
      return true
    })
  }, [teams, domainFilter, query])

  if (authLoading) return <div className="mx-auto max-w-6xl px-6 py-14"><Spinner /></div>

  if (!user) {
    return (
      <div className="mx-auto max-w-6xl px-6 py-14">
        <PageHeader title="Teams" description="Work on a project together — team workspaces need an account." />
        <EmptyState title="Sign in to see your teams" hint="Team workspaces are the one part of this app that needs an account.">
          <Link to="/account" className="btn-primary t-label-caps inline-block px-4 py-2">
            Sign in
          </Link>
        </EmptyState>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-6xl px-6 py-14">
      <div className="mb-8 flex flex-wrap items-start justify-between gap-6">
        <div className="min-w-0">
          <span className="t-label-caps flex items-center gap-1.5" style={{ color: 'var(--outline)', fontSize: 10 }}>
            <span className="h-1 w-1 rounded-full" style={{ background: 'var(--primary)' }} />
            Directory Index · Teams
          </span>
          <h1 className="t-headline-lg mt-3" style={{ color: 'var(--primary)' }}>
            Your Teams
          </h1>
          <p className="t-body-md mt-3 max-w-xl" style={{ color: 'var(--on-surface-variant)' }}>
            Shared workspaces for the projects you're building — an invite code, a message board, and everyone on the same page.
          </p>
        </div>

        <TeamAccessPanel onJoined={() => load()} />
      </div>

      {status === 'done' && teams.length > 0 && (
        <div className="mb-6 flex flex-wrap items-center gap-3">
          <div className="flex flex-wrap items-center gap-1 p-1" style={{ background: 'var(--surface-container-low)', borderRadius: 10 }}>
            <button
              onClick={() => setDomainFilter('all')}
              className="t-label-caps px-3 py-1.5 transition"
              style={
                domainFilter === 'all'
                  ? { background: 'var(--primary)', color: 'var(--on-primary)', borderRadius: 8 }
                  : { color: 'var(--on-surface-variant)', borderRadius: 8 }
              }
            >
              All domains
            </button>
            {domains.map((d) => (
              <button
                key={d}
                onClick={() => setDomainFilter(d)}
                className="t-label-caps px-3 py-1.5 transition"
                style={
                  domainFilter === d
                    ? { background: 'var(--primary)', color: 'var(--on-primary)', borderRadius: 8 }
                    : { color: 'var(--on-surface-variant)', borderRadius: 8 }
                }
              >
                {d}
              </button>
            ))}
          </div>

          <div className="relative ml-auto w-full max-w-xs">
            <svg
              className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2"
              style={{ color: 'var(--outline)' }}
              fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"
            >
              <circle cx="11" cy="11" r="7" />
              <path strokeLinecap="round" d="M21 21l-4.3-4.3" />
            </svg>
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Filter teams…"
              aria-label="Filter teams"
              className="gm-input w-full py-2 pl-9 pr-3 text-sm"
            />
          </div>
        </div>
      )}

      {status === 'loading' && <Spinner />}
      {status === 'error' && <ErrorNotice message={error} onRetry={load} />}
      {status === 'done' && teams.length === 0 && (
        <EmptyState title="No teams yet" hint="Open a project and start a team, or join one with an invite code." />
      )}
      {status === 'done' && teams.length > 0 && filtered.length === 0 && (
        <EmptyState title="No teams match that filter" hint="Try a different domain, or clear the search." />
      )}
      {status === 'done' && filtered.length > 0 && (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {filtered.map((team, i) => (
            <TeamTile key={team.team_id} team={team} featured={i === 0} />
          ))}
          <DomainDistribution teams={teams} />
        </div>
      )}
    </div>
  )
}
