import { beforeEach, describe, expect, it, vi } from 'vitest'
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
const deferred = () => {
  let resolve, reject
  const promise = new Promise((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

const OWNER = { user_id: 'owner', name: 'Olive' }
const ANN = { user_id: 'ann', name: 'Ann' }
const BOB = { user_id: 'bob', name: 'Bob' }
const TEAM = { team_id: 't1', name: 'Parent', owner_user_id: 'owner', members: [OWNER, ANN, BOB] }
const BASE = { sub_team_id: 's1', parent_team_id: 't1', name: 'Backend', module: '', description: '', status: 'active', member_count: 2, members: [ANN, BOB] }
const OWNER_SUB = { ...BASE, can_manage: true, is_member: false, invite: { active: false } }
const MEMBER_SUB = { ...BASE, can_manage: false, is_member: true }

const task = (id, title, over = {}) => ({
  task_id: id, sub_team_id: 's1', title, description: `${title} details`, status: 'todo',
  assignee: null, needs_reassignment: false, can_update_status: true, ...over,
})
const A = () => task('k1', 'Build API')
const B = () => task('k2', 'Write docs')

beforeEach(() => {
  vi.resetAllMocks()
  vi.spyOn(console, 'error').mockImplementation(() => {})
  vi.mocked(api.subTeamMessages).mockResolvedValue({ data: [], has_more: false })
  window.confirm = vi.fn(() => true)
})

async function openTasks(user, sub, tasks, props = {}) {
  vi.mocked(api.getSubTeam).mockResolvedValue({ data: sub })
  vi.mocked(api.subTeamTasks).mockResolvedValue({ data: tasks })
  const view = render(<SubTeamPanel team={TEAM} user={user} subId="s1" rosterKey="o|a|b" onClose={() => {}} onChanged={() => {}} onDeleted={() => {}} onAccessLost={() => {}} {...props} />)
  const ev = userEvent.setup()
  await ev.click(await screen.findByRole('tab', { name: 'Tasks' }))
  await screen.findByLabelText('Tasks')
  return { ev, view }
}
const editButton = (title) => screen.getByRole('button', { name: `Edit task ${title}` })
const form = (title) => screen.getByRole('form', { name: `Edit task ${title}` })
const titleField = () => screen.getByLabelText('Edit task title')
const descField = () => screen.getByLabelText('Edit task description')

describe('editing a task (owner)', () => {
  it('opens an edit form prefilled with the existing title and description', async () => {
    const { ev } = await openTasks(OWNER, OWNER_SUB, [A(), task('k2', 'No notes', { description: '' })])
    await ev.click(editButton('Build API'))
    expect(form('Build API')).toBeInTheDocument()
    expect(titleField()).toHaveValue('Build API')
    expect(descField()).toHaveValue('Build API details')
    expect(titleField()).toHaveFocus() // keyboard users land in the form
    expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument()
    await ev.click(screen.getByRole('button', { name: 'Cancel' }))

    await ev.click(editButton('No notes'))
    expect(descField()).toHaveValue('') // a task with no description starts empty
  })

  it('saves through updateSubTeamTask, updates only that task in place, and confirms', async () => {
    const { ev } = await openTasks(OWNER, OWNER_SUB, [A(), B()])
    const loads = api.subTeamTasks.mock.calls.length
    vi.mocked(api.updateSubTeamTask).mockResolvedValue({ data: { ...A(), title: 'Build the API', description: 'REST endpoints' } })

    await ev.click(editButton('Build API'))
    await ev.clear(titleField())
    await ev.type(titleField(), '  Build the API  ')
    await ev.clear(descField())
    await ev.type(descField(), 'REST endpoints')
    await ev.click(screen.getByRole('button', { name: 'Save' }))

    expect(api.updateSubTeamTask).toHaveBeenCalledTimes(1)
    expect(api.updateSubTeamTask).toHaveBeenCalledWith('t1', 's1', 'k1', { title: 'Build the API', description: 'REST endpoints' }) // trimmed
    expect(await screen.findByText('Build the API')).toBeInTheDocument()
    expect(screen.getByText('REST endpoints')).toBeInTheDocument()
    expect(screen.queryByRole('form', { name: /Edit task/ })).not.toBeInTheDocument() // closed
    expect(screen.getByRole('status')).toHaveTextContent('Saved “Build the API”.')
    // The other task is untouched, and nothing was reloaded.
    expect(screen.getByText('Write docs')).toBeInTheDocument()
    expect(screen.getByText('Write docs details')).toBeInTheDocument()
    expect(api.subTeamTasks.mock.calls.length).toBe(loads)
    expect(screen.queryByText('Build API', { exact: true })).not.toBeInTheDocument()
  })

  it('sends only the fields that changed, and nothing at all when nothing changed', async () => {
    const { ev } = await openTasks(OWNER, OWNER_SUB, [A()])
    vi.mocked(api.updateSubTeamTask).mockResolvedValue({ data: { ...A(), description: 'New notes' } })
    await ev.click(editButton('Build API'))
    await ev.clear(descField())
    await ev.type(descField(), 'New notes')
    await ev.click(screen.getByRole('button', { name: 'Save' }))
    expect(api.updateSubTeamTask).toHaveBeenLastCalledWith('t1', 's1', 'k1', { description: 'New notes' })

    api.updateSubTeamTask.mockClear()
    await ev.click(editButton('Build API'))
    await ev.click(screen.getByRole('button', { name: 'Save' })) // unchanged
    expect(api.updateSubTeamTask).not.toHaveBeenCalled()
    expect(screen.queryByRole('form', { name: /Edit task/ })).not.toBeInTheDocument()
  })

  it('allows clearing the description', async () => {
    const { ev } = await openTasks(OWNER, OWNER_SUB, [A()])
    vi.mocked(api.updateSubTeamTask).mockResolvedValue({ data: { ...A(), description: '' } })
    await ev.click(editButton('Build API'))
    await ev.clear(descField())
    await ev.click(screen.getByRole('button', { name: 'Save' }))
    expect(api.updateSubTeamTask).toHaveBeenCalledWith('t1', 's1', 'k1', { description: '' })
    expect(screen.queryByText('Build API details')).not.toBeInTheDocument()
  })

  it('cancel discards the edits, makes no request, and returns focus to the Edit button', async () => {
    const { ev } = await openTasks(OWNER, OWNER_SUB, [A(), B()])
    await ev.click(editButton('Build API'))
    await ev.clear(titleField())
    await ev.type(titleField(), 'Something else')
    await ev.type(descField(), ' more')
    await ev.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(api.updateSubTeamTask).not.toHaveBeenCalled()
    expect(screen.getByText('Build API')).toBeInTheDocument()
    expect(screen.queryByText('Something else')).not.toBeInTheDocument()
    expect(editButton('Build API')).toHaveFocus()
    await ev.click(editButton('Build API'))
    expect(titleField()).toHaveValue('Build API') // reopening starts from the stored task, not the abandoned draft
    expect(descField()).toHaveValue('Build API details')
  })

  it('Escape cancels from the keyboard', async () => {
    const { ev } = await openTasks(OWNER, OWNER_SUB, [A()])
    await ev.click(editButton('Build API'))
    await ev.type(titleField(), ' changed')
    await ev.keyboard('{Escape}')
    expect(screen.queryByRole('form', { name: /Edit task/ })).not.toBeInTheDocument()
    expect(api.updateSubTeamTask).not.toHaveBeenCalled()
    expect(screen.getByText('Build API')).toBeInTheDocument()
  })

  it('typing in the description does not pull focus back to the title', async () => {
    const { ev } = await openTasks(OWNER, OWNER_SUB, [A()])
    await ev.click(editButton('Build API'))
    await ev.click(descField())
    await ev.type(descField(), ' and more')
    expect(descField()).toHaveFocus()
    expect(descField()).toHaveValue('Build API details and more')
  })

  it('a failed save keeps the form and the typed text, leaves the task unchanged, and can be retried', async () => {
    const { ev } = await openTasks(OWNER, OWNER_SUB, [A(), B()])
    vi.mocked(api.updateSubTeamTask).mockRejectedValueOnce(apiError(500, 'Server hiccup'))
    await ev.click(editButton('Build API'))
    await ev.clear(titleField())
    await ev.type(titleField(), 'Renamed')
    await ev.click(screen.getByRole('button', { name: 'Save' }))

    expect(await within(form('Build API')).findByRole('alert')).toHaveTextContent('Server hiccup')
    expect(titleField()).toHaveValue('Renamed') // the owner's text survives
    expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled() // and they can try again
    expect(screen.getByText('Write docs')).toBeInTheDocument()

    vi.mocked(api.updateSubTeamTask).mockResolvedValueOnce({ data: { ...A(), title: 'Renamed' } })
    await ev.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByText('Renamed')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('a failed save never changes the stored task: cancelling afterwards shows the original', async () => {
    const { ev } = await openTasks(OWNER, OWNER_SUB, [A()])
    vi.mocked(api.updateSubTeamTask).mockRejectedValue(apiError(400, 'The title must be 120 characters or fewer.'))
    await ev.click(editButton('Build API'))
    await ev.type(titleField(), ' v2')
    await ev.click(screen.getByRole('button', { name: 'Save' }))
    await screen.findByRole('alert')
    await ev.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.getByText('Build API')).toBeInTheDocument()
    expect(screen.getByText('Build API details')).toBeInTheDocument()
    expect(screen.queryByText('Build API v2')).not.toBeInTheDocument()
  })

  it('validates before sending: required title, 120-character title, 1000-character description', async () => {
    const { ev } = await openTasks(OWNER, OWNER_SUB, [A()])
    await ev.click(editButton('Build API'))
    await ev.clear(titleField())
    await ev.type(titleField(), '   ')
    await ev.click(screen.getByRole('button', { name: 'Save' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Give the task a title.')
    expect(titleField()).toHaveAttribute('aria-invalid', 'true')

    fireEvent.change(titleField(), { target: { value: 'x'.repeat(121) } }) // past the input's own maxLength
    await ev.click(screen.getByRole('button', { name: 'Save' }))
    expect(screen.getByRole('alert')).toHaveTextContent('120 characters or fewer')

    fireEvent.change(titleField(), { target: { value: 'ok' } })
    fireEvent.change(descField(), { target: { value: 'd'.repeat(1001) } })
    await ev.click(screen.getByRole('button', { name: 'Save' }))
    expect(screen.getByRole('alert')).toHaveTextContent('1000 characters or fewer')
    expect(api.updateSubTeamTask).not.toHaveBeenCalled()
    expect(titleField()).toHaveAttribute('maxlength', '120')
    expect(descField()).toHaveAttribute('maxlength', '1000')

    fireEvent.change(descField(), { target: { value: 'd'.repeat(1000) } }) // exactly the limit is fine
    vi.mocked(api.updateSubTeamTask).mockResolvedValue({ data: { ...A(), title: 'ok', description: 'd'.repeat(1000) } })
    await ev.click(screen.getByRole('button', { name: 'Save' }))
    expect(api.updateSubTeamTask).toHaveBeenCalledTimes(1)
  })

  it('every edit control has an accessible name and the form is reachable by keyboard', async () => {
    const { ev } = await openTasks(OWNER, OWNER_SUB, [A()])
    await ev.click(editButton('Build API'))
    for (const name of ['Edit task title', 'Edit task description']) expect(screen.getByLabelText(name)).toBeInTheDocument()
    await ev.tab()
    expect(descField()).toHaveFocus()
    await ev.tab()
    expect(screen.getByRole('button', { name: 'Save' })).toHaveFocus()
    await ev.tab()
    expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus()
    // Enter in the title submits the form (an unchanged form just closes).
    await ev.click(titleField())
    await ev.keyboard('{Enter}')
    expect(screen.queryByRole('form', { name: /Edit task/ })).not.toBeInTheDocument()
  })
})

describe('who can edit', () => {
  it('a member who is not the owner sees no edit, delete or create controls', async () => {
    await openTasks(ANN, MEMBER_SUB, [task('k1', 'Mine', { assignee: { user_id: 'ann', name: 'Ann' } }), task('k2', 'Bobs', { can_update_status: false })])
    expect(screen.queryByRole('button', { name: /^Edit task/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument()
    expect(screen.queryByLabelText('New task title')).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/^Assignee of/)).not.toBeInTheDocument()
  })

  it('an archived sub-team exposes no edit controls even to the owner', async () => {
    await openTasks(OWNER, { ...OWNER_SUB, status: 'archived' }, [task('k1', 'Build API', { can_update_status: false })])
    expect(screen.getByText('Build API')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Edit task/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument()
    expect(screen.queryByLabelText('New task title')).not.toBeInTheDocument()
  })

  it('an assignee can still change only the status of their own task', async () => {
    const mine = task('k1', 'Mine', { assignee: { user_id: 'ann', name: 'Ann' } })
    const { ev } = await openTasks(ANN, MEMBER_SUB, [mine, task('k2', 'Bobs', { can_update_status: false, assignee: { user_id: 'bob', name: 'Bob' } })])
    vi.mocked(api.updateSubTeamTask).mockResolvedValue({ data: { ...mine, status: 'done' } })
    await ev.selectOptions(screen.getByLabelText('Status of Mine'), 'done')
    expect(api.updateSubTeamTask).toHaveBeenCalledWith('t1', 's1', 'k1', { status: 'done' }) // status only
    expect(await screen.findByDisplayValue('Done')).toBeInTheDocument()
    expect(screen.queryByLabelText('Status of Bobs')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Edit task/ })).not.toBeInTheDocument()
  })

  it('the owner keeps assignment, status and deletion alongside editing', async () => {
    const { ev } = await openTasks(OWNER, OWNER_SUB, [A()])
    vi.mocked(api.updateSubTeamTask).mockResolvedValueOnce({ data: { ...A(), assignee: { user_id: 'bob', name: 'Bob' } } })
    await ev.selectOptions(screen.getByLabelText('Assignee of Build API'), 'bob')
    expect(api.updateSubTeamTask).toHaveBeenLastCalledWith('t1', 's1', 'k1', { assignee_id: 'bob' })
    vi.mocked(api.updateSubTeamTask).mockResolvedValueOnce({ data: { ...A(), status: 'blocked' } })
    await ev.selectOptions(screen.getByLabelText('Status of Build API'), 'blocked')
    expect(api.updateSubTeamTask).toHaveBeenLastCalledWith('t1', 's1', 'k1', { status: 'blocked' })
    vi.mocked(api.deleteSubTeamTask).mockResolvedValue({ data: { deleted: true } })
    await ev.click(screen.getByRole('button', { name: 'Delete' }))
    expect(api.deleteSubTeamTask).toHaveBeenCalledWith('t1', 's1', 'k1')
  })
})

describe('duplicate submissions and concurrent actions', () => {
  it('ignores a repeated save while the first is in flight', async () => {
    const { ev } = await openTasks(OWNER, OWNER_SUB, [A()])
    const slow = deferred()
    vi.mocked(api.updateSubTeamTask).mockReturnValue(slow.promise)
    await ev.click(editButton('Build API'))
    await ev.type(titleField(), ' v2')
    const save = screen.getByRole('button', { name: 'Save' })
    fireEvent.click(save)
    fireEvent.click(save)
    fireEvent.submit(form('Build API'))
    fireEvent.submit(form('Build API'))
    expect(api.updateSubTeamTask).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('button', { name: 'Saving…' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled() // cannot abandon a save in progress
    await act(async () => { slow.resolve({ data: { ...A(), title: 'Build API v2' } }) })
    expect(await screen.findByText('Build API v2')).toBeInTheDocument()
    expect(api.updateSubTeamTask).toHaveBeenCalledTimes(1)
  })

  it('an action finishing does not clear the busy state of a different, still-running action', async () => {
    const { ev } = await openTasks(OWNER, OWNER_SUB, [A(), B()])
    const first = deferred()
    const second = deferred()
    vi.mocked(api.updateSubTeamTask).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)

    await ev.selectOptions(screen.getByLabelText('Status of Build API'), 'in_progress')
    await ev.selectOptions(screen.getByLabelText('Status of Write docs'), 'blocked')
    expect(screen.getByLabelText('Status of Build API')).toBeDisabled()
    expect(screen.getByLabelText('Status of Write docs')).toBeDisabled()

    await act(async () => { first.resolve({ data: { ...A(), status: 'in_progress' } }) })
    expect(screen.getByLabelText('Status of Build API')).toBeEnabled() // the first one is done
    expect(screen.getByLabelText('Status of Write docs')).toBeDisabled() // the second is still running
    expect(editButton('Write docs')).toBeDisabled()

    await act(async () => { second.resolve({ data: { ...B(), status: 'blocked' } }) })
    expect(screen.getByLabelText('Status of Write docs')).toBeEnabled()
    expect(editButton('Write docs')).toBeEnabled()
  })

  it('creating a task and changing another task at the same time keep separate busy states', async () => {
    const { ev } = await openTasks(OWNER, OWNER_SUB, [A()])
    const create = deferred()
    const change = deferred()
    vi.mocked(api.createSubTeamTask).mockReturnValue(create.promise)
    vi.mocked(api.updateSubTeamTask).mockReturnValue(change.promise)
    await ev.type(screen.getByLabelText('New task title'), 'Deploy')
    await ev.click(screen.getByRole('button', { name: 'Add task' }))
    await ev.selectOptions(screen.getByLabelText('Status of Build API'), 'done')
    expect(screen.getByRole('button', { name: 'Add task' })).toBeDisabled()

    await act(async () => { change.resolve({ data: { ...A(), status: 'done' } }) })
    expect(screen.getByLabelText('Status of Build API')).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Add task' })).toBeDisabled() // creation is still in flight

    await act(async () => { create.resolve({ data: task('k3', 'Deploy') }) })
    expect(await screen.findByText('Deploy')).toBeInTheDocument()
    expect(screen.getByLabelText('New task title')).toHaveValue('')
  })

  it('a failure of one action does not hide or break another task', async () => {
    const { ev } = await openTasks(OWNER, OWNER_SUB, [A(), B()])
    vi.mocked(api.updateSubTeamTask).mockRejectedValueOnce(apiError(500, 'Server hiccup')).mockResolvedValueOnce({ data: { ...B(), status: 'done' } })
    await ev.selectOptions(screen.getByLabelText('Status of Build API'), 'done')
    expect(await screen.findByRole('alert')).toHaveTextContent('Server hiccup')
    expect(screen.getByLabelText('Status of Build API')).toHaveValue('todo') // unchanged: the select shows the stored value
    await ev.selectOptions(screen.getByLabelText('Status of Write docs'), 'done')
    expect(await screen.findByDisplayValue('Done')).toBeInTheDocument()
  })
})

describe('keeping tasks fresh', () => {
  it('reopening the Tasks tab reloads the list', async () => {
    const { ev } = await openTasks(OWNER, OWNER_SUB, [A()])
    const loads = api.subTeamTasks.mock.calls.length
    await ev.click(screen.getByRole('tab', { name: 'Members' }))
    vi.mocked(api.subTeamTasks).mockResolvedValue({ data: [A(), B()] })
    await ev.click(screen.getByRole('tab', { name: 'Tasks' }))
    expect(await screen.findByText('Write docs')).toBeInTheDocument()
    expect(api.subTeamTasks.mock.calls.length).toBe(loads + 1)
  })

  it('re-reads the tasks, without a loading flash, when the sub-team roster changes', async () => {
    const { ev, view } = await openTasks(OWNER, OWNER_SUB, [A(), B()])
    const loads = api.subTeamTasks.mock.calls.length
    await ev.click(editButton('Build API'))
    await ev.type(titleField(), ' draft') // an unsaved edit is in progress
    // Bob left the parent team: the server unassigned his task; the panel re-reads the sub-team.
    vi.mocked(api.getSubTeam).mockResolvedValue({ data: { ...OWNER_SUB, members: [ANN], member_count: 1 } })
    vi.mocked(api.subTeamTasks).mockResolvedValue({ data: [A(), { ...B(), title: 'Write docs', needs_reassignment: true }] })
    view.rerender(<SubTeamPanel team={TEAM} user={OWNER} subId="s1" rosterKey="o|a" onClose={() => {}} onChanged={() => {}} onDeleted={() => {}} onAccessLost={() => {}} />)

    expect(await screen.findByText(/no longer on this sub-team/)).toBeInTheDocument()
    expect(api.subTeamTasks.mock.calls.length).toBe(loads + 1)
    expect(screen.queryByText('Loading tasks…')).not.toBeInTheDocument()
    expect(titleField()).toHaveValue('Build API draft') // the owner's draft survived the refresh
  })

  it('a refresh that was already in flight cannot undo a save that finished after it started', async () => {
    const { ev, view } = await openTasks(OWNER, OWNER_SUB, [A()])
    const staleRead = deferred()
    vi.mocked(api.getSubTeam).mockResolvedValue({ data: { ...OWNER_SUB, members: [ANN], member_count: 1 } })
    vi.mocked(api.subTeamTasks).mockReturnValue(staleRead.promise) // the refresh will answer late, with the OLD title
    view.rerender(<SubTeamPanel team={TEAM} user={OWNER} subId="s1" rosterKey="o|a" onClose={() => {}} onChanged={() => {}} onDeleted={() => {}} onAccessLost={() => {}} />)
    await act(async () => { await Promise.resolve() })

    vi.mocked(api.updateSubTeamTask).mockResolvedValue({ data: { ...A(), title: 'Build the API' } })
    await ev.click(editButton('Build API'))
    await ev.clear(titleField())
    await ev.type(titleField(), 'Build the API')
    await ev.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByText('Build the API')).toBeInTheDocument()

    await act(async () => { staleRead.resolve({ data: [A()] }) }) // arrives after the save
    expect(screen.getByText('Build the API')).toBeInTheDocument() // not reverted
    expect(screen.queryByText('Build API', { exact: true })).not.toBeInTheDocument()
  })

  it('a save that is refused because access ended hands over to the access-ended handling', async () => {
    const { ev } = await openTasks(OWNER, OWNER_SUB, [A()])
    vi.mocked(api.updateSubTeamTask).mockRejectedValue(apiError(404, 'No sub-team found.'))
    vi.mocked(api.getSubTeam).mockRejectedValue(apiError(404))
    await ev.click(editButton('Build API'))
    await ev.type(titleField(), ' x')
    await ev.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByLabelText('Sub-team access ended')).toBeInTheDocument()
    expect(screen.queryByText('Build API')).not.toBeInTheDocument()
  })
})
