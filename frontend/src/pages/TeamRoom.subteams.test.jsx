import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { AuthProvider } from '../hooks/useAuth.jsx'
import TeamRoom from './TeamRoom'
import api from '../services/api'

vi.mock('../services/api', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    default: Object.fromEntries(Object.keys(actual.default).map((key) => [key, vi.fn()])),
  }
})

const TEAM = {
  team_id: 't1', name: 'Parent Team', owner_user_id: 'u1', project_id: 'pm-1', project_title: 'Campus Marketplace', domain: 'Web Development',
  created_at: '2026-03-01T00:00:00+00:00', invite_code: 'ABC234',
  members: [{ user_id: 'u1', name: 'Alex' }, { user_id: 'u2', name: 'Sam' }],
  project: { domain: 'Web Development', difficulty: 'Intermediate', technologies: ['React'] },
}

function renderRoom() {
  window.localStorage.setItem('projectmind.authToken', 'tok-1')
  return render(
    <MemoryRouter initialEntries={['/teams/t1']}>
      <AuthProvider>
        <Routes>
          <Route path="/teams/:id" element={<TeamRoom />} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.resetAllMocks()
  window.localStorage.clear()
  vi.mocked(api.me).mockResolvedValue({ data: { user_id: 'u1', name: 'Alex', email: 'alex@example.com' } })
  vi.mocked(api.getTeam).mockResolvedValue({ data: TEAM })
  vi.mocked(api.teamMessages).mockResolvedValue({ data: [{ message_id: 'm1', user_id: 'u2', author_name: 'Sam', content: 'parent hello', created_at: '2026-03-02T10:00:00+00:00' }] })
})

describe('TeamRoom with sub-teams', () => {
  it('keeps the parent room fully working when the sub-team endpoint fails', async () => {
    vi.mocked(api.listSubTeams).mockRejectedValueOnce(new Error('Sub-teams unavailable')).mockResolvedValueOnce({ data: [] })
    const user = userEvent.setup()
    renderRoom()
    expect(await screen.findByText('parent hello')).toBeInTheDocument()
    expect(await screen.findByText('Sub-teams unavailable')).toBeInTheDocument()
    expect(screen.getByLabelText('Message your team')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Suggest roles' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByText(/No sub-teams yet/)).toBeInTheDocument()
  })

  it('shows the sub-team section with owner-only creation inside the existing room', async () => {
    vi.mocked(api.listSubTeams).mockResolvedValue({ data: [] })
    renderRoom()
    expect(await screen.findByLabelText('Sub-teams')).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: 'New sub-team' })).toBeInTheDocument()
    expect(api.listSubTeams).toHaveBeenCalledWith('t1')
  })

  it('does not offer sub-team creation to a non-owner member', async () => {
    vi.mocked(api.me).mockResolvedValue({ data: { user_id: 'u2', name: 'Sam', email: 'sam@example.com' } })
    vi.mocked(api.getTeam).mockResolvedValue({ data: { ...TEAM, invite_code: undefined } })
    vi.mocked(api.listSubTeams).mockResolvedValue({ data: [] })
    renderRoom()
    expect(await screen.findByLabelText('Sub-teams')).toBeInTheDocument()
    await screen.findByText(/The team owner creates them/)
    expect(screen.queryByRole('button', { name: 'New sub-team' })).not.toBeInTheDocument()
  })
})
