import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import SubTeams from './SubTeams'
import api from '../services/api'

vi.mock('../services/api', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    default: Object.fromEntries(Object.keys(actual.default).map((key) => [key, vi.fn()])),
  }
})

// The real panel is covered by RoleFitPanel.test.jsx; here we only check what SubTeams passes it.
vi.mock('./RoleFitPanel', () => ({
  default: ({ teamId, subTeamId }) => <div data-testid="role-panel">roles for {teamId}/{subTeamId}</div>,
}))

const TEAM = {
  team_id: 't1',
  name: 'Parent Team',
  owner_user_id: 'owner',
  members: [
    { user_id: 'owner', name: 'Olive' },
    { user_id: 'ann', name: 'Ann' },
    { user_id: 'bob', name: 'Bob' },
  ],
}
const OWNER = { user_id: 'owner', name: 'Olive' }
const ANN = { user_id: 'ann', name: 'Ann' }
const BOB = { user_id: 'bob', name: 'Bob' }

const summary = (over = {}) => ({
  sub_team_id: 's1', parent_team_id: 't1', name: 'Backend', module: 'API', description: 'Server side', status: 'active',
  member_count: 1, is_member: true, can_manage: false, ...over,
})
const detail = (over = {}) => ({
  ...summary(), members: [{ user_id: 'ann', name: 'Ann' }], ...over,
})
const ownerDetail = (over = {}) => detail({ can_manage: true, is_member: false, invite: { active: false, expires_at: null }, ...over })

beforeEach(() => {
  vi.resetAllMocks()
  window.confirm = vi.fn(() => true)
})

function setup(user, subs, extra = {}) {
  vi.mocked(api.listSubTeams).mockResolvedValue({ data: subs })
  vi.mocked(api.subTeamMessages).mockResolvedValue({ data: [], has_more: false })
  vi.mocked(api.subTeamTasks).mockResolvedValue({ data: [] })
  if (extra.detail) vi.mocked(api.getSubTeam).mockResolvedValue({ data: extra.detail })
  return render(<SubTeams team={TEAM} user={user} />)
}

describe('SubTeams list and creation', () => {
  it('shows a loading state, then an owner-oriented empty state with the create control', async () => {
    setup(OWNER, [])
    expect(screen.getByText('Loading sub-teams…')).toBeInTheDocument()
    expect(await screen.findByText(/No sub-teams yet\. Create one/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'New sub-team' })).toBeInTheDocument()
  })

  it('does not offer creation to an ordinary member and explains who creates sub-teams', async () => {
    setup(ANN, [])
    expect(await screen.findByText(/The team owner creates them/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'New sub-team' })).not.toBeInTheDocument()
  })

  it('shows an error with retry, independent of the rest of the room', async () => {
    vi.mocked(api.listSubTeams).mockRejectedValueOnce(new Error('Server hiccup')).mockResolvedValueOnce({ data: [summary()] })
    const user = userEvent.setup()
    render(<SubTeams team={TEAM} user={ANN} />)
    expect(await screen.findByText('Server hiccup')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByText('Backend')).toBeInTheDocument()
  })

  it('validates the name, then creates a sub-team with the chosen parent members', async () => {
    setup(OWNER, [])
    vi.mocked(api.createSubTeam).mockResolvedValue({ data: summary({ sub_team_id: 's9', name: 'Frontend', can_manage: true, is_member: false }) })
    vi.mocked(api.getSubTeam).mockResolvedValue({ data: ownerDetail({ sub_team_id: 's9', name: 'Frontend' }) })
    const user = userEvent.setup()
    await screen.findByText(/No sub-teams yet/)
    await user.click(screen.getByRole('button', { name: 'New sub-team' }))
    await user.click(screen.getByRole('button', { name: 'Create sub-team' }))
    expect(await screen.findByText('Give the sub-team a name.')).toBeInTheDocument()
    expect(api.createSubTeam).not.toHaveBeenCalled()

    await user.type(screen.getByLabelText('Sub-team name'), 'Frontend')
    await user.click(screen.getByLabelText('Ann'))
    await user.click(screen.getByRole('button', { name: 'Create sub-team' }))
    await waitFor(() => expect(api.createSubTeam).toHaveBeenCalledWith('t1', { name: 'Frontend', module: '', description: '', member_ids: ['ann'] }))
    expect(await screen.findByLabelText('Sub-team Frontend')).toBeInTheDocument()
  })

  it('shows the server’s reason when creation is refused', async () => {
    setup(OWNER, [])
    vi.mocked(api.createSubTeam).mockRejectedValue(new Error('A sub-team with that name already exists.'))
    const user = userEvent.setup()
    await screen.findByText(/No sub-teams yet/)
    await user.click(screen.getByRole('button', { name: 'New sub-team' }))
    await user.type(screen.getByLabelText('Sub-team name'), 'Backend')
    await user.click(screen.getByRole('button', { name: 'Create sub-team' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('already exists')
  })

  it('lets a non-member see a sub-team exists but not open it', async () => {
    setup(BOB, [summary({ is_member: false, member_count: 3 })])
    expect(await screen.findByText('Backend')).toBeInTheDocument()
    expect(screen.getByText(/Members only/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Open Backend' })).not.toBeInTheDocument()
  })

  it('joins with a sub-team code and opens that sub-team; shows the generic error otherwise', async () => {
    setup(BOB, [])
    vi.mocked(api.joinSubTeam).mockRejectedValueOnce(new Error('Invalid or expired invite code.')).mockResolvedValueOnce({ data: summary() })
    vi.mocked(api.getSubTeam).mockResolvedValue({ data: detail() })
    const user = userEvent.setup()
    await screen.findByText(/no sub-teams yet/i)
    await user.type(screen.getByLabelText('Sub-team invite code'), 'abcd234567')
    await user.click(screen.getByRole('button', { name: 'Join sub-team' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid or expired invite code.')
    await user.click(screen.getByRole('button', { name: 'Join sub-team' }))
    expect(api.joinSubTeam).toHaveBeenLastCalledWith('ABCD234567')
    expect(await screen.findByLabelText('Sub-team Backend')).toBeInTheDocument()
  })
})

describe('Sub-team panel', () => {
  async function open(user, userObj, sd) {
    setup(userObj, [summary({ can_manage: sd.can_manage, is_member: sd.is_member })], { detail: sd })
    await user.click(await screen.findByRole('button', { name: 'Open Backend' }))
    return screen.findByLabelText('Sub-team Backend')
  }

  it('chat: shows messages, sends, and keeps a failed send inline', async () => {
    vi.mocked(api.subTeamMessages).mockResolvedValue({ data: [], has_more: false })
    const user = userEvent.setup()
    await open(user, ANN, detail())
    vi.mocked(api.subTeamMessages).mockResolvedValue({
      data: [{ message_id: 'm1', user_id: 'bob', author_name: 'Bob', content: 'hello team', created_at: '2026-03-04T10:00:00+00:00' }],
      has_more: true,
    })
    // reopen chat tab to reload with messages
    await user.click(screen.getByRole('tab', { name: 'Members' }))
    await user.click(screen.getByRole('tab', { name: 'Chat' }))
    expect(await screen.findByText('hello team')).toBeInTheDocument()
    expect(screen.getByText('Load earlier messages')).toBeInTheDocument()
    expect(screen.getByText(/separate/i)).toBeInTheDocument()

    vi.mocked(api.postSubTeamMessage).mockRejectedValueOnce(new Error('Rate limit hit')).mockResolvedValueOnce({
      data: { message_id: 'm2', user_id: 'ann', author_name: 'Ann', content: 'on it', created_at: '2026-03-04T10:01:00+00:00' },
    })
    await user.type(screen.getByLabelText('Message this sub-team'), 'on it')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Rate limit hit')
    expect(screen.getByText('hello team')).toBeInTheDocument() // the panel is still there
    expect(screen.getByLabelText('Message this sub-team')).toHaveValue('on it') // draft kept for retry
    await user.click(screen.getByRole('button', { name: 'Send' }))
    expect(await screen.findByText('on it')).toBeInTheDocument()
    expect(api.postSubTeamMessage).toHaveBeenLastCalledWith('t1', 's1', 'on it')
  })

  it('chat: an owner who is not in the sub-team cannot read it and can add themselves', async () => {
    const user = userEvent.setup()
    await open(user, OWNER, ownerDetail())
    expect(screen.getByText(/private to the sub-team/)).toBeInTheDocument()
    expect(api.subTeamMessages).not.toHaveBeenCalled()
    vi.mocked(api.addSubTeamMember).mockResolvedValue({ data: ownerDetail({ is_member: true }) })
    await user.click(screen.getByRole('button', { name: 'Add me to this sub-team' }))
    expect(api.addSubTeamMember).toHaveBeenCalledWith('t1', 's1', 'owner')
  })

  it('chat: an archived sub-team is read-only', async () => {
    const user = userEvent.setup()
    await open(user, ANN, detail({ status: 'archived' }))
    expect(screen.getByText(/Archived — read only/)).toBeInTheDocument()
    expect(await screen.findByLabelText('Message this sub-team')).toBeDisabled()
  })

  it('chat: does not poll while the page is hidden', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
      await open(user, ANN, detail())
      await screen.findByLabelText('Message this sub-team')
      const calls = api.subTeamMessages.mock.calls.length
      Object.defineProperty(document, 'hidden', { configurable: true, get: () => true })
      await vi.advanceTimersByTimeAsync(16000)
      expect(api.subTeamMessages.mock.calls.length).toBe(calls)
      Object.defineProperty(document, 'hidden', { configurable: true, get: () => false })
      await vi.advanceTimersByTimeAsync(6000)
      expect(api.subTeamMessages.mock.calls.length).toBeGreaterThan(calls)
    } finally {
      Object.defineProperty(document, 'hidden', { configurable: true, get: () => false })
      vi.useRealTimers()
    }
  })

  it('tasks: the owner manages tasks; deleting asks for confirmation', async () => {
    const user = userEvent.setup()
    await open(user, OWNER, ownerDetail())
    vi.mocked(api.subTeamTasks).mockResolvedValue({
      data: [{ task_id: 'k1', title: 'Build API', description: '', status: 'todo', assignee: { user_id: 'ann', name: 'Ann' }, needs_reassignment: false, can_update_status: true }],
    })
    await user.click(screen.getByRole('tab', { name: 'Tasks' }))
    expect(await screen.findByText('Build API')).toBeInTheDocument()
    expect(screen.getByLabelText('New task title')).toBeInTheDocument()

    vi.mocked(api.createSubTeamTask).mockResolvedValue({ data: { task_id: 'k2', title: 'Write docs', description: '', status: 'todo', assignee: null, needs_reassignment: false, can_update_status: true } })
    await user.type(screen.getByLabelText('New task title'), 'Write docs')
    await user.click(screen.getByRole('button', { name: 'Add task' }))
    expect(await screen.findByText('Write docs')).toBeInTheDocument()
    expect(api.createSubTeamTask).toHaveBeenCalledWith('t1', 's1', { title: 'Write docs', assignee_id: null })

    window.confirm = vi.fn(() => false)
    await user.click(screen.getAllByRole('button', { name: 'Delete' })[0])
    expect(api.deleteSubTeamTask).not.toHaveBeenCalled()
    window.confirm = vi.fn(() => true)
    vi.mocked(api.deleteSubTeamTask).mockResolvedValue({ data: { deleted: true } })
    await user.click(screen.getAllByRole('button', { name: 'Delete' })[0])
    await waitFor(() => expect(api.deleteSubTeamTask).toHaveBeenCalledWith('t1', 's1', 'k1'))
    await waitFor(() => expect(screen.queryByText('Build API')).not.toBeInTheDocument())
  })

  it('tasks: an assignee may change only their own task’s status; others see read-only values', async () => {
    const user = userEvent.setup()
    await open(user, ANN, detail())
    vi.mocked(api.subTeamTasks).mockResolvedValue({
      data: [
        { task_id: 'k1', title: 'Mine', status: 'todo', assignee: { user_id: 'ann', name: 'Ann' }, needs_reassignment: false, can_update_status: true },
        { task_id: 'k2', title: 'Bobs', status: 'blocked', assignee: { user_id: 'bob', name: 'Bob' }, needs_reassignment: false, can_update_status: false },
        { task_id: 'k3', title: 'Orphaned', status: 'todo', assignee: null, needs_reassignment: true, can_update_status: false },
      ],
    })
    vi.mocked(api.updateSubTeamTask).mockResolvedValue({
      data: { task_id: 'k1', title: 'Mine', status: 'done', assignee: { user_id: 'ann', name: 'Ann' }, needs_reassignment: false, can_update_status: true },
    })
    await user.click(screen.getByRole('tab', { name: 'Tasks' }))
    expect(await screen.findByText('Mine')).toBeInTheDocument()
    expect(screen.queryByLabelText('New task title')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument()
    expect(screen.getByLabelText('Status of Mine')).toBeInTheDocument()
    expect(screen.queryByLabelText('Status of Bobs')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Assignee of Mine')).not.toBeInTheDocument()
    expect(screen.getByText('Assigned to you')).toBeInTheDocument()
    expect(screen.getByText(/no longer on this sub-team\./)).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('Status of Mine'), 'done')
    expect(api.updateSubTeamTask).toHaveBeenCalledWith('t1', 's1', 'k1', { status: 'done' })
  })

  it('tasks: empty and error states', async () => {
    const user = userEvent.setup()
    await open(user, ANN, detail())
    vi.mocked(api.subTeamTasks).mockRejectedValueOnce(new Error('Tasks unavailable')).mockResolvedValueOnce({ data: [] })
    await user.click(screen.getByRole('tab', { name: 'Tasks' }))
    expect(await screen.findByText('Tasks unavailable')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByText(/No tasks have been added/)).toBeInTheDocument()
  })

  it('roles: loads for this sub-team only and passes the sub-team id to the panel', async () => {
    const user = userEvent.setup()
    await open(user, ANN, detail())
    vi.mocked(api.subTeamRoles).mockResolvedValue({ data: { role_fit: { members: [] } } })
    await user.click(screen.getByRole('tab', { name: 'Roles' }))
    expect(screen.getByText(/only\. A teammate’s saved profile is used only if/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Suggest roles for this sub-team' }))
    expect(await screen.findByTestId('role-panel')).toHaveTextContent('roles for t1/s1')
    expect(api.subTeamRoles).toHaveBeenCalledWith('t1', 's1')
  })

  it('members: an ordinary member sees the roster but no management controls', async () => {
    const user = userEvent.setup()
    await open(user, ANN, detail())
    await user.click(screen.getByRole('tab', { name: 'Members' }))
    const roster = await screen.findByLabelText('Sub-team members')
    expect(within(roster).getByText('Ann')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Remove/ })).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Sub-team settings')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Sub-team invitation')).not.toBeInTheDocument()
  })

  it('members: the owner adds, removes, renames, archives and deletes', async () => {
    const user = userEvent.setup()
    await open(user, OWNER, ownerDetail())
    await user.click(screen.getByRole('tab', { name: 'Members' }))
    vi.mocked(api.addSubTeamMember).mockResolvedValue({ data: ownerDetail({ members: [{ user_id: 'ann', name: 'Ann' }, { user_id: 'bob', name: 'Bob' }], member_count: 2 }) })
    await user.click(await screen.findByRole('button', { name: '+ Bob' }))
    expect(api.addSubTeamMember).toHaveBeenCalledWith('t1', 's1', 'bob')
    expect(await screen.findByRole('button', { name: 'Remove Bob from this sub-team' })).toBeInTheDocument()

    vi.mocked(api.removeSubTeamMember).mockResolvedValue({ data: ownerDetail() })
    await user.click(screen.getByRole('button', { name: 'Remove Bob from this sub-team' }))
    expect(api.removeSubTeamMember).toHaveBeenCalledWith('t1', 's1', 'bob')

    vi.mocked(api.updateSubTeam).mockResolvedValue({ data: ownerDetail({ name: 'Backend v2' }) })
    const name = screen.getByLabelText('Sub-team name')
    await user.clear(name)
    await user.type(name, 'Backend v2')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(api.updateSubTeam).toHaveBeenCalledWith('t1', 's1', { name: 'Backend v2', module: 'API', description: 'Server side' })

    vi.mocked(api.updateSubTeam).mockResolvedValue({ data: ownerDetail({ status: 'archived' }) })
    await user.click(screen.getByRole('button', { name: 'Archive' }))
    expect(api.updateSubTeam).toHaveBeenLastCalledWith('t1', 's1', { status: 'archived' })

    window.confirm = vi.fn(() => false)
    await user.click(screen.getByRole('button', { name: 'Delete sub-team' }))
    expect(api.deleteSubTeam).not.toHaveBeenCalled()
    window.confirm = vi.fn(() => true)
    vi.mocked(api.deleteSubTeam).mockResolvedValue({ data: { deleted: true } })
    await user.click(screen.getByRole('button', { name: 'Delete sub-team' }))
    await waitFor(() => expect(api.deleteSubTeam).toHaveBeenCalledWith('t1', 's1'))
    await waitFor(() => expect(screen.queryByLabelText('Sub-team Backend')).not.toBeInTheDocument())
  })

  it('members: the invitation code is shown once, can be rotated and revoked, and is never listed', async () => {
    const user = userEvent.setup()
    await open(user, OWNER, ownerDetail())
    await user.click(screen.getByRole('tab', { name: 'Members' }))
    vi.mocked(api.createSubTeamInvite).mockResolvedValue({ data: ownerDetail({ invite: { active: true, expires_at: '2026-04-01T00:00:00+00:00', code: 'ABCDE23456' } }) })
    await user.selectOptions(await screen.findByLabelText('Invitation validity in days'), '3')
    await user.click(screen.getByRole('button', { name: 'Create code' }))
    expect(await screen.findByLabelText('New invitation code')).toHaveTextContent('ABCDE23456')
    expect(api.createSubTeamInvite).toHaveBeenCalledWith('t1', 's1', 3)
    expect(screen.getByText(/not shown again/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Rotate code' })).toBeInTheDocument()

    vi.mocked(api.revokeSubTeamInvite).mockResolvedValue({ data: ownerDetail() })
    await user.click(screen.getByRole('button', { name: 'Revoke' }))
    await waitFor(() => expect(screen.queryByLabelText('New invitation code')).not.toBeInTheDocument())
    expect(screen.getByText(/There is no active code/)).toBeInTheDocument()
  })

  it('shows the server’s error when a management action is refused', async () => {
    const user = userEvent.setup()
    await open(user, OWNER, ownerDetail())
    await user.click(screen.getByRole('tab', { name: 'Members' }))
    vi.mocked(api.addSubTeamMember).mockRejectedValue(new Error('That person is not a member of the parent team.'))
    await user.click(await screen.findByRole('button', { name: '+ Bob' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('not a member of the parent team')
  })

  it('shows an error with retry if the sub-team cannot be loaded', async () => {
    setup(ANN, [summary()])
    vi.mocked(api.getSubTeam).mockRejectedValueOnce(new Error('Gone')).mockResolvedValueOnce({ data: detail() })
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Open Backend' }))
    expect(await screen.findByText('Gone')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByLabelText('Sub-team Backend')).toBeInTheDocument()
  })
})
