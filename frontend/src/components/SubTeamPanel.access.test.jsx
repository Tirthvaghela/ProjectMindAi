import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import SubTeamPanel from './SubTeamPanel'
import SubTeams from './SubTeams'
import api from '../services/api'

vi.mock('../services/api', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    default: Object.fromEntries(Object.keys(actual.default).map((key) => [key, vi.fn()])),
  }
})
vi.mock('./RoleFitPanel', () => ({ default: () => null }))

const apiError = (status, message = 'request failed') => Object.assign(new Error(message), { status })
const networkError = () => Object.assign(new Error('Cannot reach the server. Is the Flask backend running?'), { status: null })

const OWNER = { user_id: 'owner', name: 'Olive' }
const ANN = { user_id: 'ann', name: 'Ann' }
const BOB = { user_id: 'bob', name: 'Bob' }
const TEAM = { team_id: 't1', name: 'Parent', owner_user_id: 'owner', members: [OWNER, ANN, BOB] }
const MEMBER_SUB = { sub_team_id: 's1', parent_team_id: 't1', name: 'Backend', module: 'API', description: '', status: 'active', member_count: 2, is_member: true, can_manage: false, members: [ANN, BOB] }
const OWNER_SUB = { ...MEMBER_SUB, is_member: false, can_manage: true, member_count: 1, members: [ANN], invite: { active: false, expires_at: null } }

const iso = (n) => new Date(Date.UTC(2026, 2, 1, 10, n)).toISOString()
const msg = (n) => ({ message_id: `m${n}`, user_id: 'bob', author_name: 'Bob', content: `text ${n}`, created_at: iso(n) })
const deferred = () => {
  let resolve, reject
  const promise = new Promise((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}
const poll = async (ms = 5000) => act(async () => { await vi.advanceTimersByTimeAsync(ms) })

beforeEach(() => {
  vi.resetAllMocks()
  vi.useFakeTimers({ shouldAdvanceTime: true })
  vi.spyOn(console, 'error').mockImplementation(() => {})
})
afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

function renderPanel(user, props = {}) {
  const handlers = { onClose: vi.fn(), onChanged: vi.fn(), onDeleted: vi.fn(), onAccessLost: vi.fn() }
  const view = render(<SubTeamPanel team={TEAM} user={user} subId="s1" rosterKey="o|a|b" {...handlers} {...props} />)
  return { ...view, ...handlers }
}
const userEv = () => userEvent.setup({ advanceTimers: vi.advanceTimersByTime })

describe('self-join (M3)', () => {
  beforeEach(() => {
    vi.mocked(api.getSubTeam).mockResolvedValue({ data: OWNER_SUB })
    vi.mocked(api.subTeamMessages).mockResolvedValue({ data: [], has_more: false })
  })

  it('shows why a failed self-join failed, next to the button, and lets the owner retry', async () => {
    vi.mocked(api.addSubTeamMember).mockRejectedValueOnce(apiError(400, 'This sub-team is archived. Reactivate it to make changes.'))
    const user = userEv()
    renderPanel(OWNER)
    await user.click(await screen.findByRole('button', { name: 'Add me to this sub-team' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('This sub-team is archived')
    expect(api.addSubTeamMember).toHaveBeenCalledWith('t1', 's1', 'owner')
    expect(screen.getByRole('button', { name: 'Add me to this sub-team' })).toBeEnabled() // can try again
  })

  it('a successful retry clears the error and makes the owner a member with a working chat', async () => {
    vi.mocked(api.addSubTeamMember)
      .mockRejectedValueOnce(apiError(500, 'Server hiccup'))
      .mockResolvedValueOnce({ data: { ...OWNER_SUB, is_member: true, member_count: 2, members: [OWNER, ANN] } })
    const user = userEv()
    const { onChanged } = renderPanel(OWNER)
    await user.click(await screen.findByRole('button', { name: 'Add me to this sub-team' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Server hiccup')

    vi.mocked(api.subTeamMessages).mockResolvedValue({ data: [msg(1)], has_more: false })
    await user.click(screen.getByRole('button', { name: 'Add me to this sub-team' }))
    expect(await screen.findByLabelText('Message this sub-team')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument() // the old error is gone
    expect(screen.queryByRole('button', { name: 'Add me to this sub-team' })).not.toBeInTheDocument()
    expect(await screen.findByText('text 1')).toBeInTheDocument()
    expect(onChanged).toHaveBeenCalledWith(expect.objectContaining({ is_member: true }))
  })

  it('ignores a second click while the request is in progress', async () => {
    const pending = deferred()
    vi.mocked(api.addSubTeamMember).mockReturnValue(pending.promise)
    renderPanel(OWNER)
    const button = await screen.findByRole('button', { name: 'Add me to this sub-team' })
    fireEvent.click(button)
    fireEvent.click(button)
    fireEvent.click(button)
    expect(api.addSubTeamMember).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('button', { name: 'Adding…' })).toBeDisabled()
    await act(async () => { pending.resolve({ data: { ...OWNER_SUB, is_member: true } }) })
    expect(api.addSubTeamMember).toHaveBeenCalledTimes(1)
  })
})

describe('access ended while the chat is open', () => {
  async function openChat(messages = [msg(11), msg(12)]) {
    vi.mocked(api.getSubTeam).mockResolvedValue({ data: MEMBER_SUB })
    vi.mocked(api.subTeamMessages).mockResolvedValueOnce({ data: messages, has_more: false })
    const view = renderPanel(ANN)
    await screen.findByText('text 11')
    return view
  }

  it.each([404, 401])('a %i poll response stops polling and hides every loaded message', async (status) => {
    const { onAccessLost } = await openChat()
    vi.mocked(api.subTeamMessages).mockRejectedValue(apiError(status))
    vi.mocked(api.getSubTeam).mockRejectedValue(apiError(status))
    await poll()

    expect(screen.queryByText('text 11')).not.toBeInTheDocument() // nothing stale left on screen
    expect(screen.queryByText('text 12')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Sub-team messages')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Message this sub-team')).not.toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent(status === 401 ? 'Your session has ended' : 'Your access to this sub-team has ended')
    expect(onAccessLost).toHaveBeenCalled() // SubTeams is told so it can refresh its list

    const calls = api.subTeamMessages.mock.calls.length
    await poll(30000)
    expect(api.subTeamMessages.mock.calls.length).toBe(calls) // polling has stopped
  })

  it('removed from the sub-team only (owner, 403): the chat is hidden and polling stops, but the panel stays for administration', async () => {
    vi.mocked(api.getSubTeam).mockResolvedValue({ data: { ...MEMBER_SUB, can_manage: true } })
    vi.mocked(api.subTeamMessages).mockResolvedValueOnce({ data: [msg(11)], has_more: false })
    renderPanel(OWNER)
    await screen.findByText('text 11')

    vi.mocked(api.subTeamMessages).mockRejectedValue(apiError(403, 'Join this sub-team to use this sub-team’s chat.'))
    vi.mocked(api.getSubTeam).mockResolvedValue({ data: { ...MEMBER_SUB, can_manage: true, is_member: false, members: [ANN] } })
    await poll()

    expect(screen.queryByText('text 11')).not.toBeInTheDocument()
    expect(screen.getByText(/private to the sub-team/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add me to this sub-team' })).toBeInTheDocument()
    expect(screen.getByLabelText('Sub-team Backend')).toBeInTheDocument() // the owner can still manage it
    const calls = api.subTeamMessages.mock.calls.length
    await poll(30000)
    expect(api.subTeamMessages.mock.calls.length).toBe(calls)
  })

  it('a removed member cannot see cached messages again, even after re-joining before the fresh load finishes', async () => {
    vi.mocked(api.getSubTeam).mockResolvedValue({ data: { ...MEMBER_SUB, can_manage: true } })
    vi.mocked(api.subTeamMessages).mockResolvedValueOnce({ data: [msg(11), msg(12)], has_more: false })
    const user = userEv()
    renderPanel(OWNER)
    await screen.findByText('text 11')
    vi.mocked(api.subTeamMessages).mockRejectedValue(apiError(403))
    vi.mocked(api.getSubTeam).mockResolvedValue({ data: { ...MEMBER_SUB, can_manage: true, is_member: false } })
    await poll()
    expect(screen.queryByText('text 11')).not.toBeInTheDocument()

    const fresh = deferred()
    vi.mocked(api.subTeamMessages).mockReset()
    vi.mocked(api.subTeamMessages).mockReturnValue(fresh.promise)
    vi.mocked(api.addSubTeamMember).mockResolvedValue({ data: { ...MEMBER_SUB, can_manage: true, is_member: true } })
    await user.click(screen.getByRole('button', { name: 'Add me to this sub-team' }))
    await screen.findByText('Loading chat…')
    expect(screen.queryByText('text 11')).not.toBeInTheDocument() // the earlier messages are gone, not merely hidden
    await act(async () => { fresh.resolve({ data: [msg(30)], has_more: false }) })
    expect(await screen.findByText('text 30')).toBeInTheDocument()
    expect(screen.queryByText('text 11')).not.toBeInTheDocument()
  })

  it('a send that is refused because access ended also clears the chat', async () => {
    const user = userEv()
    await openChat()
    vi.mocked(api.postSubTeamMessage).mockRejectedValue(apiError(404))
    vi.mocked(api.getSubTeam).mockRejectedValue(apiError(404))
    await user.type(screen.getByLabelText('Message this sub-team'), 'hello')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    expect(await screen.findByText('Your access to this sub-team has ended.', { exact: false })).toBeInTheDocument()
    expect(screen.queryByText('text 11')).not.toBeInTheDocument()
  })

  it('"Check again" restarts the chat if access turns out to be fine', async () => {
    const user = userEv()
    await openChat()
    vi.mocked(api.subTeamMessages).mockRejectedValueOnce(apiError(404))
    vi.mocked(api.getSubTeam).mockResolvedValue({ data: MEMBER_SUB }) // the panel confirms we are still a member
    await poll()
    expect(await screen.findByRole('button', { name: 'Check again' })).toBeInTheDocument()
    expect(screen.queryByText('text 11')).not.toBeInTheDocument()

    vi.mocked(api.subTeamMessages).mockResolvedValue({ data: [msg(11)], has_more: false })
    await user.click(screen.getByRole('button', { name: 'Check again' }))
    expect(await screen.findByText('text 11')).toBeInTheDocument()
  })

  it('while the ended notice is shown (panel still mounted) polling stays stopped and nothing stale is kept', async () => {
    const user = userEv()
    await openChat([msg(11), msg(12)])
    vi.mocked(api.subTeamMessages).mockRejectedValue(apiError(404))
    vi.mocked(api.getSubTeam).mockResolvedValue({ data: MEMBER_SUB }) // still a member as far as the panel knows
    await poll()
    expect(await screen.findByRole('button', { name: 'Check again' })).toBeInTheDocument()
    const calls = api.subTeamMessages.mock.calls.length
    await poll(30000)
    expect(api.subTeamMessages.mock.calls.length).toBe(calls) // no polling behind the notice

    // Checking again loads a different history: none of the earlier messages may be mixed back in.
    vi.mocked(api.subTeamMessages).mockReset()
    vi.mocked(api.subTeamMessages).mockResolvedValue({ data: [msg(30)], has_more: false })
    await user.click(screen.getByRole('button', { name: 'Check again' }))
    expect(await screen.findByText('text 30')).toBeInTheDocument()
    expect(screen.queryByText('text 11')).not.toBeInTheDocument()
    expect(screen.queryByText('text 12')).not.toBeInTheDocument()
  })

  it('a tasks request that returns 404 also ends the panel instead of showing a retry loop', async () => {
    vi.mocked(api.getSubTeam).mockResolvedValue({ data: MEMBER_SUB })
    vi.mocked(api.subTeamMessages).mockResolvedValue({ data: [], has_more: false })
    const user = userEv()
    renderPanel(ANN)
    await screen.findByLabelText('Message this sub-team')
    vi.mocked(api.subTeamTasks).mockRejectedValue(apiError(404))
    vi.mocked(api.getSubTeam).mockRejectedValue(apiError(404))
    await user.click(screen.getByRole('tab', { name: 'Tasks' }))
    expect(await screen.findByLabelText('Sub-team access ended')).toBeInTheDocument()
    expect(screen.queryByLabelText('Sub-team Backend')).not.toBeInTheDocument()
  })
})

describe('temporary failures are not revoked access', () => {
  async function openChat() {
    vi.mocked(api.getSubTeam).mockResolvedValue({ data: MEMBER_SUB })
    vi.mocked(api.subTeamMessages).mockResolvedValueOnce({ data: [msg(11), msg(12)], has_more: false })
    const view = renderPanel(ANN)
    await screen.findByText('text 11')
    return view
  }

  it.each([
    ['a network failure', () => networkError()],
    ['a 500', () => apiError(500, 'Internal server error.')],
    ['a 429', () => apiError(429, 'Too many requests')],
    ['a timeout', () => Object.assign(new Error('The server took too long to respond.'), { status: null })],
  ])('%s keeps the messages, keeps polling and recovers by itself', async (_label, make) => {
    const { onAccessLost } = await openChat()
    vi.mocked(api.subTeamMessages).mockRejectedValue(make())
    await poll()
    expect(screen.getByText('text 11')).toBeInTheDocument() // still shown
    expect(screen.getByRole('status')).toHaveTextContent('Trying again')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument() // not reported as lost access
    expect(onAccessLost).not.toHaveBeenCalled()
    expect(api.getSubTeam).toHaveBeenCalledTimes(1) // no revalidation was triggered either

    const calls = api.subTeamMessages.mock.calls.length
    vi.mocked(api.subTeamMessages).mockResolvedValue({ data: [msg(11), msg(12), msg(13)], has_more: false })
    await poll()
    expect(api.subTeamMessages.mock.calls.length).toBe(calls + 1) // polling carried on
    expect(screen.getByText('text 13')).toBeInTheDocument()
    expect(screen.queryByRole('status')).not.toBeInTheDocument() // the note cleared itself
  })

  it('a failed revalidation caused by the network does not end the panel', async () => {
    vi.mocked(api.getSubTeam).mockResolvedValue({ data: { ...MEMBER_SUB, can_manage: true } })
    vi.mocked(api.subTeamMessages).mockResolvedValueOnce({ data: [msg(11)], has_more: false })
    renderPanel(OWNER)
    await screen.findByText('text 11')
    vi.mocked(api.subTeamMessages).mockRejectedValue(apiError(403))
    vi.mocked(api.getSubTeam).mockRejectedValue(networkError()) // cannot confirm anything
    await poll()
    expect(screen.queryByLabelText('Sub-team access ended')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Sub-team Backend')).toBeInTheDocument()
  })
})

describe('parent roster changes', () => {
  const summary = (over = {}) => ({ ...MEMBER_SUB, members: undefined, ...over })
  const FIVE = { ...TEAM, members: [OWNER, ANN, BOB] }
  const WITHOUT_BOB = { ...TEAM, members: [OWNER, ANN] }

  function setup(team = FIVE, user = OWNER) {
    vi.mocked(api.listSubTeams).mockResolvedValue({ data: [summary({ can_manage: true, is_member: true, member_count: 3 })] })
    vi.mocked(api.getSubTeam).mockResolvedValue({ data: { ...MEMBER_SUB, can_manage: true, member_count: 3, members: [OWNER, ANN, BOB], invite: { active: false } } })
    vi.mocked(api.subTeamMessages).mockResolvedValue({ data: [], has_more: false })
    return render(<SubTeams team={team} user={user} />)
  }

  it('refreshes the list and the open panel when the set of parent members changes', async () => {
    const user = userEv()
    const view = setup()
    await user.click(await screen.findByRole('button', { name: 'Open Backend' }))
    await screen.findByLabelText('Sub-team Backend')
    await user.click(screen.getByRole('tab', { name: 'Members' }))
    expect(await screen.findByRole('button', { name: 'Remove Bob from this sub-team' })).toBeInTheDocument()
    expect(screen.getByText('3 members')).toBeInTheDocument()
    const listCalls = api.listSubTeams.mock.calls.length
    const detailCalls = api.getSubTeam.mock.calls.length

    // The owner removed Bob from the parent team: the server has already cleaned up.
    vi.mocked(api.listSubTeams).mockResolvedValue({ data: [summary({ can_manage: true, is_member: true, member_count: 2 })] })
    vi.mocked(api.getSubTeam).mockResolvedValue({ data: { ...MEMBER_SUB, can_manage: true, member_count: 2, members: [OWNER, ANN], invite: { active: false } } })
    view.rerender(<SubTeams team={WITHOUT_BOB} user={OWNER} />)

    expect(await screen.findByText('2 members')).toBeInTheDocument() // the card's count
    expect(api.listSubTeams.mock.calls.length).toBe(listCalls + 1)
    expect(api.getSubTeam.mock.calls.length).toBe(detailCalls + 1)
    // No stale controls for the person who is gone.
    expect(await screen.findByLabelText('Sub-team members')).not.toHaveTextContent('Bob')
    expect(screen.queryByRole('button', { name: 'Remove Bob from this sub-team' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Remove Ann from this sub-team' })).toBeInTheDocument()
  })

  it('does not reload for changes that leave the roster the same (rename, skills, new object identity)', async () => {
    const user = userEv()
    const view = setup()
    await user.click(await screen.findByRole('button', { name: 'Open Backend' }))
    await screen.findByLabelText('Sub-team Backend')
    const listCalls = api.listSubTeams.mock.calls.length
    const detailCalls = api.getSubTeam.mock.calls.length
    view.rerender(<SubTeams team={{ ...FIVE, name: 'Renamed', members: FIVE.members.map((m) => ({ ...m, skills: ['x'] })) }} user={OWNER} />)
    view.rerender(<SubTeams team={{ ...FIVE, members: [BOB, OWNER, ANN] }} user={OWNER} />) // same people, different order
    await poll(100)
    expect(api.listSubTeams.mock.calls.length).toBe(listCalls)
    expect(api.getSubTeam.mock.calls.length).toBe(detailCalls)
  })

  it('refreshes quietly: the list and open panel stay on screen while it reloads', async () => {
    const user = userEv()
    const view = setup()
    await user.click(await screen.findByRole('button', { name: 'Open Backend' }))
    await screen.findByLabelText('Sub-team Backend')
    const slowList = deferred()
    const slowDetail = deferred()
    vi.mocked(api.listSubTeams).mockReturnValue(slowList.promise)
    vi.mocked(api.getSubTeam).mockReturnValue(slowDetail.promise)
    view.rerender(<SubTeams team={WITHOUT_BOB} user={OWNER} />)
    await act(async () => { await Promise.resolve() })
    expect(screen.getByText('Backend', { selector: 'p' })).toBeInTheDocument() // card still there
    expect(screen.getByLabelText('Sub-team Backend')).toBeInTheDocument() // panel still there
    expect(screen.queryByText('Loading sub-teams…')).not.toBeInTheDocument()
    expect(screen.queryByText('Loading sub-team…')).not.toBeInTheDocument()
    await act(async () => {
      slowList.resolve({ data: [summary({ can_manage: true, is_member: true, member_count: 2 })] })
      slowDetail.resolve({ data: { ...MEMBER_SUB, can_manage: true, member_count: 2, members: [OWNER, ANN] } })
    })
    expect(await screen.findByText('2 members')).toBeInTheDocument()
  })

  it('a refresh that fails because of the network keeps what is shown', async () => {
    const view = setup()
    await screen.findByText('Backend', { selector: 'p' })
    vi.mocked(api.listSubTeams).mockRejectedValue(networkError())
    view.rerender(<SubTeams team={WITHOUT_BOB} user={OWNER} />)
    await act(async () => { await Promise.resolve() })
    expect(screen.getByText('Backend', { selector: 'p' })).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('if the refresh shows the user has lost the whole team, the section and open panel are replaced by a notice', async () => {
    const user = userEv()
    const view = setup(FIVE, ANN)
    vi.mocked(api.listSubTeams).mockResolvedValue({ data: [summary({ can_manage: false, is_member: true })] })
    await user.click(await screen.findByRole('button', { name: 'Open Backend' }))
    await screen.findByLabelText('Message this sub-team')
    vi.mocked(api.listSubTeams).mockRejectedValue(apiError(404, 'No team found, or you are not a member.'))
    vi.mocked(api.getSubTeam).mockRejectedValue(apiError(404))
    view.rerender(<SubTeams team={{ ...FIVE, members: [OWNER, BOB] }} user={ANN} />)
    expect(await screen.findByText(/You no longer have access to this team’s sub-teams/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Sub-team Backend')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Sub-teams list')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'New sub-team' })).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Sub-team invite code')).not.toBeInTheDocument()
  })

  it('a poll-detected loss of access in the open chat refreshes the list', async () => {
    const user = userEv()
    setup(FIVE, ANN)
    vi.mocked(api.listSubTeams).mockResolvedValue({ data: [summary({ can_manage: false, is_member: true })] })
    vi.mocked(api.getSubTeam).mockResolvedValue({ data: MEMBER_SUB })
    vi.mocked(api.subTeamMessages).mockResolvedValueOnce({ data: [msg(11)], has_more: false })
    await user.click(await screen.findByRole('button', { name: 'Open Backend' }))
    await screen.findByText('text 11')
    const listCalls = api.listSubTeams.mock.calls.length
    vi.mocked(api.subTeamMessages).mockRejectedValue(apiError(404))
    vi.mocked(api.getSubTeam).mockRejectedValue(apiError(404))
    vi.mocked(api.listSubTeams).mockResolvedValue({ data: [] }) // the sub-team is no longer listed for her
    await poll()
    expect(await screen.findByLabelText('Sub-team access ended')).toBeInTheDocument()
    expect(api.listSubTeams.mock.calls.length).toBe(listCalls + 1)
    expect(screen.queryByText('text 11')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Close' }))
    expect(screen.queryByLabelText('Sub-team access ended')).not.toBeInTheDocument()
    expect(within(screen.getByLabelText('Sub-teams')).getByText(/no sub-teams yet/i)).toBeInTheDocument()
  })
})
