import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
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

// --- a tiny scroll model: jsdom has no layout, so rows are 100px tall inside a 300px viewport ---------------
const ROW = 100
const VIEW = 300
const tops = new WeakMap()
const rowCount = (el) => el.querySelectorAll('[data-message-id]').length
beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, 'scrollHeight', { configurable: true, get() { return rowCount(this) * ROW } })
  Object.defineProperty(HTMLElement.prototype, 'clientHeight', { configurable: true, get() { return VIEW } })
  Object.defineProperty(HTMLElement.prototype, 'scrollTop', {
    configurable: true,
    get() { return tops.get(this) ?? 0 },
    set(value) { tops.set(this, Math.max(0, Math.min(value, Math.max(0, this.scrollHeight - VIEW)))) }, // browsers clamp
  })
})
afterAll(() => {
  delete HTMLElement.prototype.scrollHeight
  delete HTMLElement.prototype.clientHeight
  delete HTMLElement.prototype.scrollTop
})

const TEAM = { team_id: 't1', name: 'Parent', owner_user_id: 'owner', members: [{ user_id: 'ann', name: 'Ann' }, { user_id: 'bob', name: 'Bob' }] }
const ANN = { user_id: 'ann', name: 'Ann' }
const SUB = { sub_team_id: 's1', parent_team_id: 't1', name: 'Backend', module: '', description: '', status: 'active', member_count: 2, is_member: true, can_manage: false, members: [{ user_id: 'ann', name: 'Ann' }, { user_id: 'bob', name: 'Bob' }] }

const iso = (n) => new Date(Date.UTC(2026, 2, 1, 10, n)).toISOString()
const msg = (n, over = {}) => ({ message_id: `m${n}`, user_id: 'bob', author_name: 'Bob', content: `text ${n}`, created_at: iso(n), ...over })
const range = (a, b) => Array.from({ length: b - a + 1 }, (_, i) => msg(a + i))
const deferred = () => {
  let resolve, reject
  const promise = new Promise((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

const list = () => screen.getByLabelText('Sub-team messages')
const ids = () => [...list().querySelectorAll('[data-message-id]')].map((el) => el.getAttribute('data-message-id'))
const expected = (a, b) => range(a, b).map((m) => m.message_id)
const poll = async (ms = 5000) => act(async () => { await vi.advanceTimersByTimeAsync(ms) })
const userScrolls = (to) => { list().scrollTop = to; fireEvent.scroll(list()) }
const tick = async () => act(async () => { await Promise.resolve() })

let consoleError
beforeEach(() => {
  vi.resetAllMocks()
  vi.useFakeTimers({ shouldAdvanceTime: true })
  vi.mocked(api.getSubTeam).mockResolvedValue({ data: SUB })
  consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
})
afterEach(() => {
  vi.useRealTimers()
  consoleError.mockRestore()
})

async function open(first = { data: range(11, 20), has_more: true }) {
  vi.mocked(api.subTeamMessages).mockResolvedValueOnce(first)
  const view = render(<SubTeamPanel team={TEAM} user={ANN} subId="s1" onClose={() => {}} onChanged={() => {}} onDeleted={() => {}} />)
  await screen.findByLabelText('Sub-team messages')
  return view
}
const noKeyWarnings = () => consoleError.mock.calls.filter((c) => String(c[0]).includes('same key') || String(c[0]).includes('unique "key"'))

describe('sub-team chat: history is never destroyed by polling', () => {
  it('keeps older messages that were loaded when the next poll arrives', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    await open()
    expect(ids()).toEqual(expected(11, 20))
    vi.mocked(api.subTeamMessages).mockResolvedValueOnce({ data: range(1, 10), has_more: false })
    await user.click(screen.getByRole('button', { name: 'Load earlier messages' }))
    expect(ids()).toEqual(expected(1, 20))
    expect(api.subTeamMessages).toHaveBeenLastCalledWith('t1', 's1', { before: iso(11) })

    vi.mocked(api.subTeamMessages).mockResolvedValue({ data: range(11, 20), has_more: true }) // the poll: newest page only
    await poll()
    expect(ids()).toEqual(expected(1, 20)) // nothing dropped, no duplicates, still chronological
    expect(screen.queryByRole('button', { name: /earlier messages/ })).not.toBeInTheDocument() // the poll did not bring "Load earlier" back
  })

  it('appends genuinely new messages from a poll exactly once, in order', async () => {
    await open()
    vi.mocked(api.subTeamMessages).mockResolvedValue({ data: range(12, 21), has_more: true })
    await poll()
    expect(ids()).toEqual(expected(11, 21))
    await poll()
    expect(ids()).toEqual(expected(11, 21))
  })

  it('orders messages chronologically even if a response arrives out of order', async () => {
    await open({ data: [msg(15), msg(13)], has_more: false })
    expect(ids()).toEqual(['m13', 'm15'])
    vi.mocked(api.subTeamMessages).mockResolvedValue({ data: [msg(14), msg(16)], has_more: false })
    await poll()
    expect(ids()).toEqual(['m13', 'm14', 'm15', 'm16'])
  })

  it('never renders a message_id twice, even within one response, and raises no duplicate-key warning', async () => {
    await open({ data: [msg(1), msg(1), msg(2)], has_more: false })
    expect(ids()).toEqual(['m1', 'm2'])
    vi.mocked(api.subTeamMessages).mockResolvedValue({ data: [msg(2), msg(2), msg(3), msg(3), { ...msg(4), message_id: undefined }], has_more: false })
    await poll()
    expect(ids()).toEqual(['m1', 'm2', 'm3']) // a malformed entry with no id is ignored
    expect(noKeyWarnings()).toHaveLength(0)
  })

  it('a failed poll leaves the loaded messages alone and does not show an error screen', async () => {
    await open()
    vi.mocked(api.subTeamMessages).mockRejectedValue(new Error('offline'))
    await poll()
    expect(ids()).toEqual(expected(11, 20))
    expect(screen.getByRole('status')).toHaveTextContent('offline') // a quiet "retrying" note, not an error screen
    expect(screen.queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('starts again from the newest page when more than a page arrived between polls', async () => {
    await open({ data: range(41, 50), has_more: true })
    vi.mocked(api.subTeamMessages).mockResolvedValue({ data: range(81, 90), has_more: true }) // no overlap: there is a hole
    await poll()
    expect(ids()).toEqual(expected(81, 90))
    expect(screen.getByRole('button', { name: 'Load earlier messages' })).toBeInTheDocument() // the hole stays reachable
  })

  it('shows the empty state and then the first messages', async () => {
    await open({ data: [], has_more: false })
    expect(screen.getByText(/No messages yet/)).toBeInTheDocument()
    vi.mocked(api.subTeamMessages).mockResolvedValue({ data: [msg(1)], has_more: false })
    await poll()
    expect(ids()).toEqual(['m1'])
    expect(screen.queryByText(/No messages yet/)).not.toBeInTheDocument()
  })
})

describe('sub-team chat: sending races with polling', () => {
  async function typeAndSend(user, text) {
    await user.type(screen.getByLabelText('Message this sub-team'), text)
    await user.click(screen.getByRole('button', { name: 'Send' }))
  }

  it('a poll that already contains the new message does not duplicate it when the send response lands', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    await open({ data: range(1, 3), has_more: false })
    const send = deferred()
    vi.mocked(api.postSubTeamMessage).mockReturnValue(send.promise)
    await typeAndSend(user, 'hello')
    const mine = msg(4, { user_id: 'ann', author_name: 'Ann', content: 'hello' })

    vi.mocked(api.subTeamMessages).mockResolvedValue({ data: [...range(1, 3), mine], has_more: false })
    await poll() // the poll sees the stored message first
    expect(ids()).toEqual(['m1', 'm2', 'm3', 'm4'])
    await act(async () => { send.resolve({ data: mine }) })
    expect(ids()).toEqual(['m1', 'm2', 'm3', 'm4']) // the send response adds nothing
    expect(noKeyWarnings()).toHaveLength(0)
    expect(screen.getByLabelText('Message this sub-team')).toHaveValue('') // draft cleared
  })

  it('a stale poll answer that predates the sent message cannot remove it', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    await open({ data: range(1, 3), has_more: false })
    const stale = deferred()
    vi.mocked(api.subTeamMessages).mockReturnValue(stale.promise)
    await poll() // a poll is now in flight and will answer without the new message
    const mine = msg(4, { user_id: 'ann', author_name: 'Ann', content: 'hello' })
    vi.mocked(api.postSubTeamMessage).mockResolvedValue({ data: mine })
    await typeAndSend(user, 'hello')
    expect(ids()).toEqual(['m1', 'm2', 'm3', 'm4'])
    await act(async () => { stale.resolve({ data: range(1, 3), has_more: false }) })
    expect(ids()).toEqual(['m1', 'm2', 'm3', 'm4']) // still there
  })

  it('a failed send is reported at the composer and keeps the draft', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    await open({ data: range(1, 3), has_more: false })
    vi.mocked(api.postSubTeamMessage).mockRejectedValue(new Error('Rate limit hit'))
    await typeAndSend(user, 'hello')
    expect(await screen.findByRole('alert')).toHaveTextContent('Rate limit hit')
    expect(within(list()).queryByRole('alert')).not.toBeInTheDocument() // not in the history area
    expect(screen.getByLabelText('Message this sub-team')).toHaveValue('hello')
  })
})

describe('sub-team chat: scrolling', () => {
  it('starts at the bottom', async () => {
    await open()
    expect(list().scrollTop).toBe(10 * ROW - VIEW)
  })

  it('keeps the reader exactly where they were when older messages are prepended', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    await open()
    userScrolls(250) // reading near the top of the loaded history
    vi.mocked(api.subTeamMessages).mockResolvedValueOnce({ data: range(1, 10), has_more: false })
    await user.click(screen.getByRole('button', { name: 'Load earlier messages' }))
    expect(ids()).toEqual(expected(1, 20))
    expect(list().scrollTop).toBe(250 + 10 * ROW) // the same message is still in the same place on screen
  })

  it('follows new messages when the reader is already at the bottom', async () => {
    await open()
    vi.mocked(api.subTeamMessages).mockResolvedValue({ data: range(12, 21), has_more: true })
    await poll()
    expect(ids()).toEqual(expected(11, 21))
    expect(list().scrollTop).toBe(11 * ROW - VIEW)
  })

  it('also follows when the reader is within the near-bottom threshold', async () => {
    await open()
    userScrolls(10 * ROW - VIEW - 40) // 40px from the bottom
    vi.mocked(api.subTeamMessages).mockResolvedValue({ data: range(12, 21), has_more: true })
    await poll()
    expect(list().scrollTop).toBe(11 * ROW - VIEW)
  })

  it('does not drag a reader who is up in the history back to the bottom', async () => {
    await open()
    userScrolls(100)
    vi.mocked(api.subTeamMessages).mockResolvedValue({ data: range(12, 22), has_more: true })
    await poll()
    expect(ids()).toEqual(expected(11, 22))
    expect(list().scrollTop).toBe(100)
  })

  it('scrolls to the bottom after the current user sends, even when reading history', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    await open()
    userScrolls(100)
    vi.mocked(api.postSubTeamMessage).mockResolvedValue({ data: msg(21, { user_id: 'ann', author_name: 'Ann', content: 'mine' }) })
    await user.type(screen.getByLabelText('Message this sub-team'), 'mine')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    expect(ids()).toEqual(expected(11, 21))
    expect(list().scrollTop).toBe(11 * ROW - VIEW)
  })

  it('does not scroll when a poll brings nothing new', async () => {
    await open()
    userScrolls(300)
    vi.mocked(api.subTeamMessages).mockResolvedValue({ data: range(11, 20), has_more: true })
    await poll()
    expect(list().scrollTop).toBe(300)
  })
})

describe('sub-team chat: pagination errors', () => {
  it('shows a failed "Load earlier" next to the history control, not as a send error, and retries without losing messages', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    await open()
    vi.mocked(api.subTeamMessages).mockRejectedValueOnce(new Error('History unavailable'))
    await user.click(screen.getByRole('button', { name: 'Load earlier messages' }))

    const alert = await within(list()).findByRole('alert') // inside the history area
    expect(alert).toHaveTextContent('Couldn’t load earlier messages: History unavailable')
    expect(screen.getAllByRole('alert')).toHaveLength(1) // and nowhere else: the composer shows no send error
    expect(ids()).toEqual(expected(11, 20)) // everything already loaded is still there
    expect(screen.getByLabelText('Message this sub-team')).toBeEnabled()

    vi.mocked(api.subTeamMessages).mockResolvedValueOnce({ data: range(1, 10), has_more: false })
    await user.click(screen.getByRole('button', { name: 'Retry loading earlier messages' }))
    expect(ids()).toEqual(expected(1, 20))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('a send error and a pagination error stay separate', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    await open()
    vi.mocked(api.subTeamMessages).mockRejectedValueOnce(new Error('History unavailable'))
    await user.click(screen.getByRole('button', { name: 'Load earlier messages' }))
    vi.mocked(api.postSubTeamMessage).mockRejectedValue(new Error('Send failed'))
    await user.type(screen.getByLabelText('Message this sub-team'), 'x')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    await screen.findByText('Send failed')
    expect(within(list()).getByRole('alert')).toHaveTextContent('History unavailable')
    expect(within(list()).queryByText('Send failed')).not.toBeInTheDocument()
  })
})

describe('sub-team chat: polling lifecycle', () => {
  it('stops polling on unmount and ignores an answer that arrives afterwards', async () => {
    const late = deferred()
    const view = await open()
    vi.mocked(api.subTeamMessages).mockReturnValue(late.promise)
    await poll() // one poll in flight
    const calls = api.subTeamMessages.mock.calls.length
    view.unmount()
    await poll(20000)
    expect(api.subTeamMessages.mock.calls.length).toBe(calls) // no further requests after unmount
    await tick()
    late.resolve({ data: range(1, 3), has_more: false }) // a late answer does nothing and does not throw
    await tick()
    expect(consoleError.mock.calls.filter((c) => String(c[0]).toLowerCase().includes('unmounted'))).toHaveLength(0)
  })

  it('keeps the five-second interval and skips polls while the page is hidden', async () => {
    await open()
    const calls = api.subTeamMessages.mock.calls.length
    vi.mocked(api.subTeamMessages).mockResolvedValue({ data: range(11, 20), has_more: true })
    await poll(4900)
    expect(api.subTeamMessages.mock.calls.length).toBe(calls) // not before five seconds
    await poll(200)
    expect(api.subTeamMessages.mock.calls.length).toBe(calls + 1)
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => true })
    await poll(15000)
    expect(api.subTeamMessages.mock.calls.length).toBe(calls + 1)
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => false })
  })
})
