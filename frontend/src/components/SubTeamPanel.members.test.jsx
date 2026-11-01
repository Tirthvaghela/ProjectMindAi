import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import SubTeamPanel from './SubTeamPanel'
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
const networkError = () => Object.assign(new Error('Cannot reach the server.'), { status: null })
const deferred = () => {
  let resolve, reject
  const promise = new Promise((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

const OWNER = { user_id: 'owner', name: 'Olive' }
const ANN = { user_id: 'ann', name: 'Ann' }
const BOB = { user_id: 'bob', name: 'Bob' }
const CY = { user_id: 'cy', name: 'Cy' }
const TEAM = { team_id: 't1', name: 'Parent', owner_user_id: 'owner', members: [OWNER, ANN, BOB, CY] }
const NO_INVITE = { active: false, expires_at: null }
const sub = (over = {}) => ({
  sub_team_id: 's1', parent_team_id: 't1', name: 'Backend', module: 'API', description: '', status: 'active',
  member_count: 1, is_member: false, can_manage: true, members: [ANN], invite: NO_INVITE, ...over,
})
const withMembers = (...members) => sub({ members, member_count: members.length })

const CODE = 'ABCDE23456'
const inFuture = (ms) => new Date(Date.now() + ms).toISOString()

beforeEach(() => {
  vi.resetAllMocks()
  vi.useFakeTimers({ shouldAdvanceTime: true })
  vi.spyOn(console, 'error').mockImplementation(() => {})
  window.confirm = vi.fn(() => true)
  vi.mocked(api.subTeamMessages).mockResolvedValue({ data: [], has_more: false })
})
afterEach(() => {
  Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true })
  vi.useRealTimers()
  vi.restoreAllMocks()
})

const userEv = () => userEvent.setup({ advanceTimers: vi.advanceTimersByTime })

async function openMembers(detail, props = {}) {
  vi.mocked(api.getSubTeam).mockResolvedValue({ data: detail })
  const handlers = { onClose: vi.fn(), onChanged: vi.fn(), onDeleted: vi.fn(), onAccessLost: vi.fn() }
  const view = render(<SubTeamPanel team={TEAM} user={OWNER} subId="s1" rosterKey="o|a|b|c" {...handlers} {...props} />)
  fireEvent.click(await screen.findByRole('tab', { name: 'Members' }))
  await screen.findByLabelText('Sub-team members')
  return { ...view, ...handlers }
}
const roster = () => within(screen.getByLabelText('Sub-team members'))

describe('adding members', () => {
  it('adds a parent-team member: calls the API, updates the roster and count, announces it, and moves focus to a stable place', async () => {
    vi.mocked(api.addSubTeamMember).mockResolvedValue({ data: withMembers(ANN, BOB) })
    const user = userEv()
    const { onChanged } = await openMembers(withMembers(ANN))
    await user.click(screen.getByRole('button', { name: '+ Bob' }))

    expect(api.addSubTeamMember).toHaveBeenCalledWith('t1', 's1', 'bob')
    expect(await roster().findByText('Bob')).toBeInTheDocument()
    expect(screen.getByText('Sub-team members (2)')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '+ Bob' })).not.toBeInTheDocument() // already on it
    expect(screen.getByRole('status')).toHaveTextContent('Bob was added.')
    expect(onChanged).toHaveBeenCalledWith(expect.objectContaining({ member_count: 2 }))
    await vi.waitFor(() => expect(screen.getByText('Sub-team members (2)')).toHaveFocus()) // the clicked button no longer exists
  })

  it('shows why an add failed, keeps the roster, keeps focus on the button and allows a retry', async () => {
    vi.mocked(api.addSubTeamMember)
      .mockRejectedValueOnce(apiError(500, 'Server hiccup'))
      .mockResolvedValueOnce({ data: withMembers(ANN, BOB) })
    const user = userEv()
    await openMembers(withMembers(ANN))
    await user.click(screen.getByRole('button', { name: '+ Bob' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Server hiccup')
    expect(roster().queryByText('Bob')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '+ Bob' })).toBeEnabled()
    await vi.waitFor(() => expect(screen.getByRole('button', { name: '+ Bob' })).toHaveFocus())
    expect(api.getSubTeam).toHaveBeenCalledTimes(1) // a 500 says nothing about access: no re-read

    await user.click(screen.getByRole('button', { name: '+ Bob' }))
    expect(await roster().findByText('Bob')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('a network failure shows the message and does not treat it as lost access', async () => {
    vi.mocked(api.addSubTeamMember).mockRejectedValue(networkError())
    const user = userEv()
    await openMembers(withMembers(ANN))
    await user.click(screen.getByRole('button', { name: '+ Bob' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Cannot reach the server.')
    expect(api.getSubTeam).toHaveBeenCalledTimes(1)
    expect(screen.getByLabelText('Sub-team invitation')).toBeInTheDocument()
  })

  it('someone who already left the parent team: the 400 triggers a re-read so the list is corrected', async () => {
    vi.mocked(api.addSubTeamMember).mockRejectedValue(apiError(400, 'That person is not a member of the parent team.'))
    const user = userEv()
    await openMembers(withMembers(ANN))
    vi.mocked(api.getSubTeam).mockResolvedValue({ data: withMembers(ANN) }) // current server state
    await user.click(screen.getByRole('button', { name: '+ Bob' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('not a member of the parent team')
    expect(api.getSubTeam).toHaveBeenCalledTimes(2)
  })

  it('an archived sub-team cannot take new members and says why', async () => {
    await openMembers(sub({ status: 'archived' }))
    expect(screen.getByRole('button', { name: '+ Bob' })).toBeDisabled()
    expect(screen.getByText('Reactivate this sub-team to add people.')).toBeInTheDocument()
  })
})

describe('removing members', () => {
  it('asks first (naming the consequence), then removes and announces it', async () => {
    vi.mocked(api.removeSubTeamMember).mockResolvedValue({ data: withMembers() })
    const user = userEv()
    const { onChanged } = await openMembers(withMembers(ANN))
    window.confirm = vi.fn(() => false)
    await user.click(screen.getByRole('button', { name: 'Remove Ann from this sub-team' }))
    expect(api.removeSubTeamMember).not.toHaveBeenCalled()
    expect(window.confirm).toHaveBeenCalledWith(expect.stringMatching(/task assignments.*unassigned.*role choice is cleared/))

    window.confirm = vi.fn(() => true)
    await user.click(screen.getByRole('button', { name: 'Remove Ann from this sub-team' }))
    expect(api.removeSubTeamMember).toHaveBeenCalledWith('t1', 's1', 'ann')
    expect(await screen.findByText('No one is on this sub-team yet.')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Ann was removed.')
    expect(onChanged).toHaveBeenCalledWith(expect.objectContaining({ member_count: 0 }))
    expect(screen.getByRole('button', { name: '+ Ann' })).toBeInTheDocument() // can be added back
  })

  it('a failed removal keeps the person listed, shows the error and returns focus to the button', async () => {
    vi.mocked(api.removeSubTeamMember).mockRejectedValue(apiError(500, 'Could not remove'))
    const user = userEv()
    await openMembers(withMembers(ANN, BOB))
    await user.click(screen.getByRole('button', { name: 'Remove Bob from this sub-team' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not remove')
    expect(roster().getByText('Bob')).toBeInTheDocument()
    await vi.waitFor(() => expect(screen.getByRole('button', { name: 'Remove Bob from this sub-team' })).toHaveFocus())
  })

  it('removing someone who has already left: the 400 re-reads, and the stale row disappears', async () => {
    vi.mocked(api.removeSubTeamMember).mockRejectedValue(apiError(400, 'That person is not on this sub-team.'))
    const user = userEv()
    await openMembers(withMembers(ANN, BOB))
    vi.mocked(api.getSubTeam).mockResolvedValue({ data: withMembers(ANN) })
    await user.click(screen.getByRole('button', { name: 'Remove Bob from this sub-team' }))
    await vi.waitFor(() => expect(roster().queryByText('Bob')).not.toBeInTheDocument())
    expect(screen.getByRole('alert')).toHaveTextContent('not on this sub-team')
    expect(screen.getByText('Sub-team members (1)')).toBeInTheDocument()
  })

  it('an ordinary member sees the roster but no management or invitation controls', async () => {
    await openMembers(sub({ can_manage: false, is_member: true, invite: undefined }))
    expect(roster().getByText('Ann')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Remove/ })).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Sub-team invitation')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Add parent-team members')).not.toBeInTheDocument()
  })
})

describe('duplicate and overlapping actions', () => {
  it('repeated clicks on one add send one request and show progress', async () => {
    const pending = deferred()
    vi.mocked(api.addSubTeamMember).mockReturnValue(pending.promise)
    await openMembers(withMembers(ANN))
    const button = screen.getByRole('button', { name: '+ Bob' })
    fireEvent.click(button)
    fireEvent.click(button)
    fireEvent.click(button)
    expect(api.addSubTeamMember).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('button', { name: 'Adding…' })).toBeDisabled()
    await act(async () => { pending.resolve({ data: withMembers(ANN, BOB) }) })
    expect(api.addSubTeamMember).toHaveBeenCalledTimes(1)
  })

  it('while one action runs every other management control waits - and they all come back afterwards', async () => {
    const pending = deferred()
    vi.mocked(api.removeSubTeamMember).mockReturnValue(pending.promise)
    await openMembers(withMembers(ANN, BOB))
    fireEvent.click(screen.getByRole('button', { name: 'Remove Ann from this sub-team' }))
    // A second action fired through the DOM anyway (a stale handler, or two quick key presses) is ignored.
    fireEvent.click(screen.getByRole('button', { name: 'Remove Bob from this sub-team' }))
    fireEvent.click(screen.getByRole('button', { name: '+ Cy' }))
    expect(api.removeSubTeamMember).toHaveBeenCalledTimes(1)
    expect(api.addSubTeamMember).not.toHaveBeenCalled()
    for (const name of [/^Remove Bob/, '+ Cy', 'Save', 'Archive', 'Create code', 'Delete sub-team']) {
      expect(screen.getByRole('button', { name })).toBeDisabled()
    }
    await act(async () => { pending.resolve({ data: withMembers(BOB) }) })
    for (const name of [/^Remove Bob/, '+ Cy', 'Save', 'Archive', 'Create code', 'Delete sub-team']) {
      expect(screen.getByRole('button', { name })).toBeEnabled()
    }
  })

  it('submitting the settings form twice, or while another action runs, sends one request (the guard does not rely on disabled buttons)', async () => {
    const pending = deferred()
    vi.mocked(api.updateSubTeam).mockReturnValue(pending.promise)
    vi.mocked(api.removeSubTeamMember).mockResolvedValue({ data: withMembers() })
    await openMembers(withMembers(ANN))
    const form = screen.getByLabelText('Sub-team settings')
    fireEvent.submit(form)
    fireEvent.submit(form)
    expect(api.updateSubTeam).toHaveBeenCalledTimes(1)
    await act(async () => { pending.resolve({ data: withMembers(ANN) }) })

    const slow = deferred()
    vi.mocked(api.updateSubTeam).mockReturnValue(slow.promise)
    fireEvent.submit(form)
    fireEvent.submit(form)
    expect(api.updateSubTeam).toHaveBeenCalledTimes(2) // one more, not two
    await act(async () => { slow.resolve({ data: withMembers(ANN) }) })
  })

  it('one action finishing does not leave another looking idle (busy state is not cleared twice)', async () => {
    const first = deferred()
    vi.mocked(api.addSubTeamMember).mockReturnValueOnce(first.promise)
    vi.mocked(api.createSubTeamInvite).mockResolvedValue({ data: sub({ invite: { active: true, expires_at: inFuture(86400000), code: CODE } }) })
    await openMembers(withMembers(ANN))
    fireEvent.click(screen.getByRole('button', { name: '+ Bob' }))
    fireEvent.click(screen.getByRole('button', { name: 'Create code' })) // ignored: an action is running
    expect(api.createSubTeamInvite).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Create code' })).toBeDisabled()
    await act(async () => { first.resolve({ data: withMembers(ANN, BOB) }) })
    expect(screen.getByRole('button', { name: 'Create code' })).toBeEnabled()
  })
})

describe('access lost during member actions', () => {
  const failWith = async (status, button = '+ Bob') => {
    vi.mocked(api.addSubTeamMember).mockRejectedValue(apiError(status, 'nope'))
    const user = userEv()
    const view = await openMembers(withMembers(ANN))
    return { user, ...view, click: () => user.click(screen.getByRole('button', { name: button })) }
  }

  it('404 and the sub-team can no longer be read: the panel ends and no private data stays on screen', async () => {
    const { click, onAccessLost } = await failWith(404)
    vi.mocked(api.getSubTeam).mockRejectedValue(apiError(404, 'Sub-team not found.'))
    await click()
    expect(await screen.findByLabelText('Sub-team access ended')).toBeInTheDocument()
    expect(screen.queryByText('Ann')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Sub-team invitation')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Sub-team members')).not.toBeInTheDocument()
    expect(onAccessLost).toHaveBeenCalled() // the list behind the panel is refreshed too
  })

  it('401: the session ended message replaces the panel', async () => {
    const { click } = await failWith(401)
    vi.mocked(api.getSubTeam).mockRejectedValue(apiError(401, 'Sign in'))
    await click()
    expect(await screen.findByRole('alert')).toHaveTextContent('Your session has ended')
    expect(screen.queryByLabelText('Sub-team members')).not.toBeInTheDocument()
  })

  it('403 (no longer the owner): the re-read removes every management control', async () => {
    const { click } = await failWith(403)
    vi.mocked(api.getSubTeam).mockResolvedValue({ data: sub({ can_manage: false, is_member: true, invite: undefined }) })
    await click()
    await vi.waitFor(() => expect(screen.queryByLabelText('Sub-team invitation')).not.toBeInTheDocument())
    expect(screen.queryByRole('button', { name: '+ Bob' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Remove/ })).not.toBeInTheDocument()
  })

  it('403 while creating a code discards any code already on screen', async () => {
    vi.mocked(api.createSubTeamInvite)
      .mockResolvedValueOnce({ data: sub({ invite: { active: true, expires_at: inFuture(86400000), code: CODE } }) })
      .mockRejectedValueOnce(apiError(403, 'Only the team owner can manage sub-teams.'))
    const user = userEv()
    await openMembers(withMembers(ANN))
    await user.click(screen.getByRole('button', { name: 'Create code' }))
    expect(await screen.findByText(CODE)).toBeInTheDocument()
    vi.mocked(api.getSubTeam).mockResolvedValue({ data: sub({ can_manage: false, is_member: true, invite: undefined }) })
    await user.click(screen.getByRole('button', { name: 'Rotate code' }))
    await vi.waitFor(() => expect(screen.queryByText(CODE)).not.toBeInTheDocument())
    expect(screen.queryByLabelText('Sub-team invitation')).not.toBeInTheDocument()
  })

  it('a re-read that cannot reach the server changes nothing', async () => {
    const { click } = await failWith(404)
    vi.mocked(api.getSubTeam).mockRejectedValue(networkError())
    await click()
    expect(await screen.findByRole('alert')).toHaveTextContent('nope')
    expect(screen.getByLabelText('Sub-team members')).toBeInTheDocument()
  })
})

describe('invitations: creating, showing and losing the code', () => {
  const created = (days = 7) => ({ data: sub({ invite: { active: true, expires_at: inFuture(days * 86400000), code: CODE } }) })

  it('shows the code once with its expiry, explains it cannot be viewed again, and moves focus to it', async () => {
    vi.mocked(api.createSubTeamInvite).mockResolvedValue(created(3))
    const user = userEv()
    await openMembers(withMembers(ANN))
    await user.selectOptions(screen.getByLabelText('Invitation validity in days'), '3')
    await user.click(screen.getByRole('button', { name: 'Create code' }))

    expect(api.createSubTeamInvite).toHaveBeenCalledWith('t1', 's1', 3)
    const group = await screen.findByRole('group', { name: 'New invitation code' })
    await vi.waitFor(() => expect(within(group).getByText(CODE)).toHaveFocus())
    expect(screen.getByText(/The current code expires /)).toBeInTheDocument()
    expect(screen.getByText(/it is not shown again, and it is lost if you leave this tab or close the panel/)).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Invitation code created')
    expect(screen.getByRole('button', { name: 'Rotate code' })).toBeInTheDocument()
  })

  it('the code is gone after leaving the Members tab and is never shown again; the listing has only the expiry', async () => {
    vi.mocked(api.createSubTeamInvite).mockResolvedValue(created())
    const user = userEv()
    await openMembers(withMembers(ANN))
    await user.click(screen.getByRole('button', { name: 'Create code' }))
    await screen.findByText(CODE)

    await user.click(screen.getByRole('tab', { name: 'Tasks' }))
    vi.mocked(api.subTeamTasks).mockResolvedValue({ data: [] })
    await user.click(screen.getByRole('tab', { name: 'Members' }))
    expect(screen.queryByText(CODE)).not.toBeInTheDocument()
    expect(screen.queryByLabelText('New invitation code')).not.toBeInTheDocument()
    expect(screen.getByText(/The current code expires /)).toBeInTheDocument() // state, not the secret
    expect(document.body.textContent).not.toContain(CODE)
  })

  it('closing and reopening the panel does not bring the code back', async () => {
    vi.mocked(api.createSubTeamInvite).mockResolvedValue(created())
    const user = userEv()
    const first = await openMembers(withMembers(ANN))
    await user.click(screen.getByRole('button', { name: 'Create code' }))
    await screen.findByText(CODE)
    first.unmount()
    vi.mocked(api.getSubTeam).mockResolvedValue({ data: sub({ invite: { active: true, expires_at: inFuture(86400000) } }) })
    render(<SubTeamPanel team={TEAM} user={OWNER} subId="s1" rosterKey="o|a|b|c" onClose={vi.fn()} onChanged={vi.fn()} onDeleted={vi.fn()} onAccessLost={vi.fn()} />)
    fireEvent.click(await screen.findByRole('tab', { name: 'Members' }))
    await screen.findByLabelText('Sub-team invitation')
    expect(document.body.textContent).not.toContain(CODE)
  })

  it('repeated clicks create exactly one invitation', async () => {
    const pending = deferred()
    vi.mocked(api.createSubTeamInvite).mockReturnValue(pending.promise)
    await openMembers(withMembers(ANN))
    const button = screen.getByRole('button', { name: 'Create code' })
    fireEvent.click(button)
    fireEvent.click(button)
    fireEvent.click(button)
    expect(api.createSubTeamInvite).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('button', { name: 'Working…' })).toBeDisabled()
    await act(async () => { pending.resolve(created()) })
    expect(api.createSubTeamInvite).toHaveBeenCalledTimes(1)
  })

  it('a failed creation shows the error, shows no code, and can be retried', async () => {
    vi.mocked(api.createSubTeamInvite)
      .mockRejectedValueOnce(apiError(500, 'Could not create an invitation - please try again.'))
      .mockResolvedValueOnce(created())
    const user = userEv()
    await openMembers(withMembers(ANN))
    await user.click(screen.getByRole('button', { name: 'Create code' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not create an invitation')
    expect(screen.queryByRole('group', { name: 'New invitation code' })).not.toBeInTheDocument()
    await vi.waitFor(() => expect(screen.getByRole('button', { name: 'Create code' })).toHaveFocus())
    await user.click(screen.getByRole('button', { name: 'Create code' }))
    expect(await screen.findByText(CODE)).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('an archived sub-team cannot create a code and says why', async () => {
    await openMembers(sub({ status: 'archived' }))
    expect(screen.getByRole('button', { name: 'Create code' })).toBeDisabled()
    expect(screen.getByText(/Archived sub-teams cannot be joined/)).toBeInTheDocument()
  })
})

describe('invitations: revoking and the states a code can be in', () => {
  const active = (extra = {}) => withMembers(ANN) && sub({ invite: { active: true, expires_at: inFuture(86400000 * 2), ...extra } })

  it('revoking removes the code and the Revoke button, says so, and puts focus on a control that still exists', async () => {
    vi.mocked(api.createSubTeamInvite).mockResolvedValue({ data: sub({ invite: { active: true, expires_at: inFuture(86400000), code: CODE } }) })
    vi.mocked(api.revokeSubTeamInvite).mockResolvedValue({ data: sub() })
    const user = userEv()
    await openMembers(withMembers(ANN))
    await user.click(screen.getByRole('button', { name: 'Create code' }))
    await screen.findByText(CODE)
    await user.click(screen.getByRole('button', { name: 'Revoke' }))

    expect(api.revokeSubTeamInvite).toHaveBeenCalledWith('t1', 's1')
    await vi.waitFor(() => expect(screen.queryByText(CODE)).not.toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'Revoke' })).not.toBeInTheDocument()
    expect(screen.getByText(/There is no active code\. The previous code was revoked\./)).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Invitation revoked')
    await vi.waitFor(() => expect(screen.getByRole('button', { name: 'Create code' })).toHaveFocus())
  })

  it('a failed revoke keeps the code and the Revoke button, and shows the error', async () => {
    vi.mocked(api.createSubTeamInvite).mockResolvedValue({ data: sub({ invite: { active: true, expires_at: inFuture(86400000), code: CODE } }) })
    vi.mocked(api.revokeSubTeamInvite).mockRejectedValue(apiError(500, 'Could not revoke'))
    const user = userEv()
    await openMembers(withMembers(ANN))
    await user.click(screen.getByRole('button', { name: 'Create code' }))
    await screen.findByText(CODE)
    await user.click(screen.getByRole('button', { name: 'Revoke' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not revoke')
    expect(screen.getByText(CODE)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Revoke' })).toBeEnabled()
  })

  it('revoking twice quickly sends one request', async () => {
    const pending = deferred()
    vi.mocked(api.revokeSubTeamInvite).mockReturnValue(pending.promise)
    await openMembers(active())
    const button = screen.getByRole('button', { name: 'Revoke' })
    fireEvent.click(button)
    fireEvent.click(button)
    expect(api.revokeSubTeamInvite).toHaveBeenCalledTimes(1)
    await act(async () => { pending.resolve({ data: sub() }) })
  })

  it('revoking when the sub-team is already gone ends the panel (404)', async () => {
    vi.mocked(api.revokeSubTeamInvite).mockRejectedValue(apiError(404, 'Sub-team not found.'))
    const user = userEv()
    await openMembers(active())
    vi.mocked(api.getSubTeam).mockRejectedValue(apiError(404, 'Sub-team not found.'))
    await user.click(screen.getByRole('button', { name: 'Revoke' }))
    expect(await screen.findByLabelText('Sub-team access ended')).toBeInTheDocument()
  })

  it('an active invitation shows when it expires, offers rotate and revoke, and never a code', async () => {
    await openMembers(active())
    expect(screen.getByText(/The current code expires .+\./)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Rotate code' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Revoke' })).toBeInTheDocument()
    expect(screen.queryByRole('group', { name: 'New invitation code' })).not.toBeInTheDocument()
  })

  it('an expired invitation is described as expired with its date, and offers only creating a new one', async () => {
    await openMembers(sub({ invite: { active: false, expired: true, expires_at: '2026-01-05T12:00:00+00:00' } }))
    expect(screen.getByText(/There is no active code\. The last one expired on .*2026/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Create code' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Rotate code' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Revoke' })).not.toBeInTheDocument()
  })

  it('a sub-team that never had a code (or whose code was revoked) says there is none', async () => {
    await openMembers(sub())
    expect(screen.getByText(/There is no active code\./)).toBeInTheDocument()
    expect(screen.queryByText(/expired/)).not.toBeInTheDocument()
    expect(screen.queryByText(/revoked/)).not.toBeInTheDocument()
  })

  it('a code that runs out while the tab is open stops being described as active', async () => {
    await openMembers(sub({ invite: { active: true, expires_at: inFuture(30000) } }))
    expect(screen.getByRole('button', { name: 'Revoke' })).toBeInTheDocument()
    await act(async () => { await vi.advanceTimersByTimeAsync(31000) })
    expect(screen.queryByRole('button', { name: 'Revoke' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Create code' })).toBeInTheDocument()
    expect(screen.getByText(/There is no active code\. The last one expired/)).toBeInTheDocument()
  })

  it('creating a code after a revoke clears the "revoked" note', async () => {
    vi.mocked(api.revokeSubTeamInvite).mockResolvedValue({ data: sub() })
    vi.mocked(api.createSubTeamInvite).mockResolvedValue({ data: sub({ invite: { active: true, expires_at: inFuture(86400000), code: CODE } }) })
    const user = userEv()
    await openMembers(active())
    await user.click(screen.getByRole('button', { name: 'Revoke' }))
    expect(await screen.findByText(/previous code was revoked/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Create code' }))
    await screen.findByText(CODE)
    expect(screen.queryByText(/previous code was revoked/)).not.toBeInTheDocument()
  })
})

describe('copying the code', () => {
  async function withCode() {
    vi.mocked(api.createSubTeamInvite).mockResolvedValue({ data: sub({ invite: { active: true, expires_at: inFuture(86400000), code: CODE } }) })
    const user = userEv()
    await openMembers(withMembers(ANN))
    await user.click(screen.getByRole('button', { name: 'Create code' }))
    await screen.findByText(CODE)
    return user
  }
  const setClipboard = (writeText) => Object.defineProperty(navigator, 'clipboard', { value: writeText ? { writeText } : undefined, configurable: true })

  it('copies the exact code and confirms it in a status message', async () => {
    const writeText = vi.fn().mockResolvedValue()
    await withCode()
    setClipboard(writeText)
    fireEvent.click(screen.getByRole('button', { name: 'Copy invitation code' }))
    await vi.waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Code copied to the clipboard.'))
    expect(writeText).toHaveBeenCalledWith(CODE)
  })

  it('a refused clipboard write says so, leaves the code selected for a manual copy, and keeps the code visible', async () => {
    await withCode()
    setClipboard(vi.fn().mockRejectedValue(new Error('denied')))
    fireEvent.click(screen.getByRole('button', { name: 'Copy invitation code' }))
    await vi.waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Could not copy automatically'))
    expect(window.getSelection().toString()).toBe(CODE)
    expect(screen.getByText(CODE)).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument() // a copy problem is not a server error
  })

  it('a browser without a clipboard API fails the same graceful way', async () => {
    await withCode()
    setClipboard(null)
    fireEvent.click(screen.getByRole('button', { name: 'Copy invitation code' }))
    await vi.waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Could not copy automatically'))
  })

  it('the copy confirmation is cleared by the next action', async () => {
    setClipboard(vi.fn().mockResolvedValue())
    vi.mocked(api.revokeSubTeamInvite).mockResolvedValue({ data: sub() })
    const user = await withCode()
    setClipboard(vi.fn().mockResolvedValue())
    fireEvent.click(screen.getByRole('button', { name: 'Copy invitation code' }))
    await vi.waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Code copied'))
    await user.click(screen.getByRole('button', { name: 'Revoke' }))
    await vi.waitFor(() => expect(screen.getByRole('status')).not.toHaveTextContent('Code copied'))
  })

  it('Copy is a real button reachable and operable from the keyboard', async () => {
    const writeText = vi.fn().mockResolvedValue()
    const user = await withCode()
    setClipboard(writeText)
    const copy = screen.getByRole('button', { name: 'Copy invitation code' })
    expect(copy.tagName).toBe('BUTTON')
    copy.focus()
    await user.keyboard('{Enter}')
    await vi.waitFor(() => expect(writeText).toHaveBeenCalledWith(CODE))
  })
})

describe('accessibility and narrow screens', () => {
  it('actions are reachable and operable by keyboard alone', async () => {
    vi.mocked(api.removeSubTeamMember).mockResolvedValue({ data: withMembers() })
    const user = userEv()
    await openMembers(withMembers(ANN))
    screen.getByRole('button', { name: 'Remove Ann from this sub-team' }).focus()
    await user.keyboard('{Enter}')
    expect(api.removeSubTeamMember).toHaveBeenCalledTimes(1)
    const add = await screen.findByRole('button', { name: '+ Ann' })
    add.focus()
    vi.mocked(api.addSubTeamMember).mockResolvedValue({ data: withMembers(ANN) })
    await user.keyboard(' ')
    expect(api.addSubTeamMember).toHaveBeenCalledWith('t1', 's1', 'ann')
  })

  it('has labelled regions and controls, a polite status region that is always present, and alerts for errors', async () => {
    vi.mocked(api.addSubTeamMember).mockRejectedValue(apiError(500, 'Server hiccup'))
    const user = userEv()
    await openMembers(withMembers(ANN))
    for (const name of ['Sub-team members', 'Add parent-team members', 'Sub-team settings', 'Sub-team invitation']) {
      expect(screen.getByLabelText(name)).toBeInTheDocument()
    }
    expect(screen.getByLabelText('Invitation validity in days')).toBeInTheDocument()
    expect(screen.getByRole('status')).toBeInTheDocument() // present before anything is announced
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '+ Bob' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Server hiccup')
  })

  it('wraps rather than overflows: long names and the code can break, rows and controls can wrap, targets have a minimum height', async () => {
    const LONG = { user_id: 'x', name: 'Bartholomew-Maximilian-Featherstonehaugh-The-Third' }
    vi.mocked(api.createSubTeamInvite).mockResolvedValue({ data: sub({ members: [LONG], member_count: 1, invite: { active: true, expires_at: inFuture(86400000), code: CODE } }) })
    const user = userEv()
    const { container } = await openMembers(sub({ members: [LONG], member_count: 1 }), { team: { ...TEAM, members: [OWNER, LONG, BOB] } })
    const row = roster().getByText(LONG.name).closest('li')
    expect(row.className).toMatch(/flex-wrap/)
    expect(roster().getByText(LONG.name).className).toMatch(/min-w-0/)
    expect(roster().getByText(LONG.name).className).toMatch(/break-words/)
    expect(within(row).getByRole('button').className).toMatch(/min-h-9/)
    expect(screen.getByRole('button', { name: '+ Bob' }).className).toMatch(/max-w-full/)
    await user.click(screen.getByRole('button', { name: 'Create code' }))
    const code = await screen.findByText(CODE)
    expect(code.className).toMatch(/break-all/)
    expect(code.parentElement.className).toMatch(/flex-wrap/)
    expect(container.querySelector('.space-y-5').className).toMatch(/min-w-0/)
  })
})
