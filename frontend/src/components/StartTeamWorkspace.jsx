import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import useAuth from '../hooks/useAuth.jsx'
import Panel from './Panel'

/**
 * Distinct from <TeamBuilder>: that one suggests roles from skills you type
 * in, stateless, no account needed. This creates a persistent, joinable
 * workspace (backend/teams/service.py) for people who actually want to
 * message each other — hence the account requirement.
 *
 * `onCreate(name) => Promise<{data}>` and `placeholderName` are the only
 * things that differ between a catalogue project (pages/ProjectDetail.jsx,
 * POST /api/teams with project_id) and a generated idea
 * (pages/IdeaDetail.jsx, POST /api/teams with idea — a generated idea has
 * no project_id, see backend/routes/ideas.py and backend/teams/service.py)
 * — both share this exact component rather than forking it.
 */
export default function StartTeamWorkspace({ placeholderName, onCreate }) {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  if (!user) {
    return (
      <Panel icon="groups" title="Team workspace" description="Sign in to start a shared team workspace — an invite code, member list, and a message board.">
        <Link to="/account" className="btn-primary t-label-caps inline-block px-4 py-2">
          Sign in
        </Link>
      </Panel>
    )
  }

  const start = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const { data } = await onCreate(name)
      navigate(`/teams/${data.team_id}`)
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  return (
    <Panel icon="groups" title="Team workspace" description="Start a shared space — an invite code your teammates can join with, and a message board.">
      <form onSubmit={start} className="flex gap-2">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={placeholderName}
          className="gm-input flex-1 px-3 py-2 text-sm"
        />
        <button type="submit" disabled={busy} className="btn-primary t-label-caps shrink-0 px-4 py-2">
          {busy ? 'Starting…' : 'Start team'}
        </button>
      </form>
      {error && <p className="t-body-md mt-2" style={{ color: '#ffb4ab', fontSize: 13 }}>{error}</p>}
    </Panel>
  )
}
