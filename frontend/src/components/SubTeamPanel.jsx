import { memo, useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import api from '../services/api'
import MarkdownLite from './MarkdownLite'
import RoleFitPanel from './RoleFitPanel'
import { Spinner, ErrorNotice } from './Feedback'
import { formatClockTime } from '../utils/time'
import { isAccessLost, isResourceGone } from '../utils/access'

const muted = { color: 'var(--on-surface-variant)' }
const errorStyle = { color: '#ffb4ab', fontSize: 12 }
const STATUS_LABEL = { todo: 'To do', in_progress: 'In progress', blocked: 'Blocked', done: 'Done' }
const TABS = [
  { key: 'chat', label: 'Chat' },
  { key: 'tasks', label: 'Tasks' },
  { key: 'roles', label: 'Roles' },
  { key: 'members', label: 'Members' },
]
const POLL_MS = 5000
// Same threshold the parent team room uses for "the reader is at the bottom".
const NEAR_BOTTOM_PX = 60
const EMPTY_VIEW = { messages: [], hasMore: false }

// The newest value of a prop, readable from callbacks without making them change identity
// (a callback that changes every render would restart polling and reload effects).
function useLatest(value) {
  const ref = useRef(value)
  useEffect(() => {
    ref.current = value
  })
  return ref
}

const ENDED_TEXT =
  'Your access to this sub-team has ended. You may have been removed from it or from the team, or it may have been deleted.'
const SESSION_ENDED_TEXT = 'Your session has ended. Sign in again to open this sub-team.'
const endedText = (status) => (status === 401 ? SESSION_ENDED_TEXT : ENDED_TEXT)

const timeOf = (message) => {
  const t = Date.parse(message.created_at)
  return Number.isNaN(t) ? 0 : t
}

/**
 * Union of `current` and `incoming` keyed by `message_id`, oldest first.
 * Messages are immutable, so an id already held is kept as is (same object, which lets
 * unchanged rows skip re-rendering). Returns `current` itself when nothing is new, so a
 * poll that found nothing causes no state change. A response can therefore never remove
 * or replace what is already shown - which is also why a stale or out-of-order response
 * is harmless.
 */
function mergeMessages(current, incoming) {
  const known = new Map(current.map((m) => [m.message_id, m]))
  let added = false
  for (const message of incoming) {
    if (message?.message_id && !known.has(message.message_id)) {
      known.set(message.message_id, message)
      added = true
    }
  }
  if (!added) return current
  return [...known.values()]
    .map((message, index) => [message, index])
    .sort(([a, i], [b, j]) => timeOf(a) - timeOf(b) || i - j)
    .map(([message]) => message)
}

const MessageItem = memo(function MessageItem({ message, mine }) {
  return (
    <div data-message-id={message.message_id} className={mine ? 'text-right' : ''}>
      <p className="t-label-mono" style={{ color: 'var(--primary)', fontSize: 11 }}>
        {mine ? 'You' : message.author_name} · {formatClockTime(message.created_at)}
      </p>
      <div className="t-body-md inline-block max-w-[85%] text-left" style={{ color: 'var(--on-surface)', fontSize: 13.5 }}>
        <MarkdownLite content={message.content} />
      </div>
    </div>
  )
})

/** Sub-team chat. Its own channel (never the parent team's), polled only while
 * this tab is open AND the page is visible. A failed send is shown right here;
 * it never replaces the room. */
function Chat({ teamId, sub, user, isMember, onJoinSelf, joining, joinError, onAccessLost }) {
  // `messages` only ever grows by union (see mergeMessages). `hasMore` means "older messages
  // exist before the oldest one shown"; polls never change it (they only fetch the newest
  // page), so only the first load, a gap reset and "Load earlier" do.
  const [view, setView] = useState(EMPTY_VIEW)
  const [status, setStatus] = useState('loading')
  const [error, setError] = useState(null)
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const [sendError, setSendError] = useState(null)
  const [loadingOlder, setLoadingOlder] = useState(false)
  const [olderError, setOlderError] = useState(null)
  const [sentCount, setSentCount] = useState(0)
  const [endedStatus, setEndedStatus] = useState(null) // HTTP status that ended access to this chat, or null
  const [recheck, setRecheck] = useState(0)
  const [pollError, setPollError] = useState(null) // a temporary refresh failure (not lost access)
  const listRef = useRef(null)
  const generation = useRef(0) // bumped on cleanup: answers from a previous poll loop are ignored
  const nearBottom = useRef(true)
  const olderAnchor = useRef(null)
  const shown = useRef([])
  const timer = useRef(null)
  const accessLost = useLatest(onAccessLost)
  const archived = sub.status === 'archived'
  const { messages, hasMore } = view

  // The server says this chat is no longer ours (removed, deleted, session gone): stop polling
  // and forget every message that was loaded, so nothing stale stays on screen.
  const endAccess = useCallback(
    (err) => {
      generation.current += 1
      clearInterval(timer.current)
      shown.current = []
      olderAnchor.current = null
      setView(EMPTY_VIEW)
      setEndedStatus(err?.status ?? 404)
      accessLost.current?.(err)
    },
    [accessLost],
  )

  const load = useCallback(async () => {
    const mine = generation.current
    try {
      const res = await api.subTeamMessages(teamId, sub.sub_team_id)
      if (mine !== generation.current) return
      const page = Array.isArray(res.data) ? res.data : []
      const pageHasMore = Boolean(res.has_more)
      setView((v) => {
        const have = new Set(v.messages.map((m) => m.message_id))
        // The newest page does not touch what we hold although older messages exist beyond it:
        // more than a page arrived between polls. Start again from the newest page (the
        // missing stretch stays reachable through "Load earlier") instead of leaving a hole.
        const gap = have.size > 0 && pageHasMore && !page.some((m) => have.has(m.message_id))
        const base = v.messages.length === 0 || gap ? [] : v.messages
        const next = mergeMessages(base, page)
        const nextHasMore = v.messages.length === 0 || gap ? pageHasMore : v.hasMore
        return next === v.messages && nextHasMore === v.hasMore ? v : { messages: next, hasMore: nextHasMore }
      })
      setError(null)
      setPollError(null)
      setStatus('done')
    } catch (err) {
      if (mine !== generation.current) return
      if (isAccessLost(err)) {
        endAccess(err)
        return
      }
      // Anything else (network, 5xx, rate limit) is treated as temporary: keep what is shown
      // and keep polling.
      setError(err.message)
      setPollError(err.message)
      setStatus((s) => (s === 'done' ? s : 'error'))
    }
  }, [teamId, sub.sub_team_id, endAccess])

  useEffect(() => {
    if (!isMember) {
      // Not (or no longer) a member: nothing from an earlier membership may linger.
      shown.current = []
      olderAnchor.current = null
      setView(EMPTY_VIEW)
      setEndedStatus(null)
      return undefined
    }
    setEndedStatus(null)
    setPollError(null)
    setStatus('loading')
    load()
    timer.current = setInterval(() => {
      if (typeof document !== 'undefined' && document.hidden) return
      load()
    }, POLL_MS)
    return () => {
      clearInterval(timer.current)
      generation.current += 1
    }
  }, [isMember, load, recheck])

  // Scrolling is decided from what actually changed:
  //   - older messages were added at the top: keep the reader exactly where they were
  //   - newer messages arrived: follow them only if the reader was already at the bottom
  //   - the first messages arrived: start at the bottom
  useLayoutEffect(() => {
    const el = listRef.current
    if (!el) return
    const previous = shown.current
    if (messages === previous) return
    shown.current = messages

    const anchor = olderAnchor.current
    olderAnchor.current = null
    const firstChanged = messages[0]?.message_id !== previous[0]?.message_id
    if (anchor && previous.length && anchor.firstId === previous[0].message_id && firstChanged) {
      el.scrollTop = anchor.top + (el.scrollHeight - anchor.height)
      return
    }
    const lastChanged = messages[messages.length - 1]?.message_id !== previous[previous.length - 1]?.message_id
    if (previous.length === 0 || (lastChanged && nearBottom.current)) {
      el.scrollTop = el.scrollHeight
      nearBottom.current = true
    }
  }, [messages])

  // After the current user's own message is stored, always show it.
  useLayoutEffect(() => {
    const el = listRef.current
    if (sentCount === 0 || !el) return
    el.scrollTop = el.scrollHeight
    nearBottom.current = true
  }, [sentCount])

  if (!isMember) {
    return (
      <div className="p-4" style={{ border: '1px solid var(--border-technical)', borderRadius: 8 }}>
        <p className="t-body-md" style={muted}>
          This chat is private to the sub-team’s members.
          {sub.can_manage && ' You manage this sub-team but are not in it, so you cannot read its chat.'}
        </p>
        {sub.can_manage && (
          <>
            <button type="button" onClick={onJoinSelf} disabled={joining} className="btn-secondary t-label-caps mt-3 px-3 py-1.5" style={{ fontSize: 10.5 }}>
              {joining ? 'Adding…' : 'Add me to this sub-team'}
            </button>
            {joinError && <p className="mt-2" role="alert" style={errorStyle}>{joinError}</p>}
          </>
        )}
      </div>
    )
  }

  if (endedStatus) {
    return (
      <div className="p-4" style={{ border: '1px solid var(--border-technical)', borderRadius: 8 }}>
        <p className="t-body-md" role="alert" style={muted}>
          {endedText(endedStatus)} The messages that were loaded have been cleared.
        </p>
        <button type="button" onClick={() => setRecheck((n) => n + 1)} className="btn-secondary t-label-caps mt-3 px-3 py-1.5" style={{ fontSize: 10.5 }}>
          Check again
        </button>
      </div>
    )
  }

  const send = async (event) => {
    event.preventDefault()
    const content = draft.trim()
    if (!content || sending) return
    setSending(true)
    setSendError(null)
    try {
      const { data } = await api.postSubTeamMessage(teamId, sub.sub_team_id, content)
      // Union by id: if a poll already delivered this message, nothing is added twice.
      setView((v) => {
        const next = mergeMessages(v.messages, [data])
        return next === v.messages ? v : { ...v, messages: next }
      })
      setSentCount((n) => n + 1)
      setDraft('')
    } catch (err) {
      if (isAccessLost(err)) endAccess(err)
      else setSendError(err.message)
    } finally {
      setSending(false)
    }
  }

  const older = async () => {
    const oldest = messages[0]
    const el = listRef.current
    if (!oldest || loadingOlder) return
    const mine = generation.current
    setLoadingOlder(true)
    setOlderError(null)
    try {
      const res = await api.subTeamMessages(teamId, sub.sub_team_id, { before: oldest.created_at })
      if (mine !== generation.current) return
      const page = Array.isArray(res.data) ? res.data : []
      // Remember where the reader is, so the layout effect can keep it after the prepend.
      if (el) olderAnchor.current = { top: el.scrollTop, height: el.scrollHeight, firstId: oldest.message_id }
      setView((v) => ({ messages: mergeMessages(v.messages, page), hasMore: Boolean(res.has_more) }))
    } catch (err) {
      if (mine === generation.current) {
        if (isAccessLost(err)) endAccess(err)
        else setOlderError(err.message)
      }
    } finally {
      setLoadingOlder(false)
    }
  }

  if (status === 'loading') return <Spinner label="Loading chat…" />
  if (status === 'error') return <ErrorNotice message={error} onRetry={load} />

  return (
    <div>
      <p className="t-label-mono mb-2" style={{ color: 'var(--outline)', fontSize: 11 }}>
        Sub-team chat — only {sub.name} members see this. The parent team’s chat is separate.
      </p>
      <div
        ref={listRef}
        onScroll={(e) => {
          const el = e.currentTarget
          nearBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM_PX
        }}
        className="h-72 space-y-2 overflow-y-auto p-3"
        style={{ background: 'var(--surface-container-low)', borderRadius: 8 }}
        aria-label="Sub-team messages"
      >
        {(hasMore || olderError) && (
          <div>
            <button type="button" onClick={older} disabled={loadingOlder} className="t-label-caps block" style={{ color: 'var(--primary)', fontSize: 10.5 }}>
              {loadingOlder ? 'Loading…' : olderError ? 'Retry loading earlier messages' : 'Load earlier messages'}
            </button>
            {olderError && <p className="mt-1" role="alert" style={errorStyle}>Couldn’t load earlier messages: {olderError}</p>}
          </div>
        )}
        {messages.length === 0 && <p className="t-body-md" style={{ ...muted, fontSize: 13 }}>No messages yet — say hello.</p>}
        {messages.map((m) => (
          <MessageItem key={m.message_id} message={m} mine={m.user_id === user.user_id} />
        ))}
      </div>
      {pollError && (
        <p className="mt-1" role="status" style={{ ...muted, fontSize: 12 }}>
          Couldn’t refresh just now ({pollError}). Trying again…
        </p>
      )}
      <form onSubmit={send} className="mt-2 flex gap-2">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={archived ? 'This sub-team is archived' : 'Message this sub-team…'}
          aria-label="Message this sub-team"
          disabled={archived}
          maxLength={2000}
          className="gm-input min-w-0 flex-1 px-3 py-2 text-sm"
        />
        <button type="submit" disabled={sending || !draft.trim() || archived} className="btn-primary t-label-caps shrink-0 px-4 py-2">
          Send
        </button>
      </form>
      {sendError && <p className="mt-1" role="alert" style={errorStyle}>{sendError}</p>}
    </div>
  )
}

// Limits the backend enforces (teams/subteams.py: MAX_TITLE_CHARS, MAX_TASK_DESCRIPTION_CHARS).
// Checked here only so the owner gets an answer without a round trip; the server re-validates.
const MAX_TASK_TITLE = 120
const MAX_TASK_DESCRIPTION = 1000

/** Tasks. The owner creates/edits/assigns/deletes; an assignee changes only the
 * status of their own task. Buttons mirror, but never replace, the server's checks. */
function Tasks({ teamId, sub, user, members, onAccessLost }) {
  const [tasks, setTasks] = useState([])
  const [status, setStatus] = useState('loading')
  const [error, setError] = useState(null)
  const [title, setTitle] = useState('')
  const [assignee, setAssignee] = useState('')
  // How many actions are in flight per key ('new', or a task id). One entry per key, so an
  // action finishing never clears another action's busy state.
  const [pending, setPending] = useState({})
  const [actionError, setActionError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [editing, setEditing] = useState(null) // { id, title, description, error } for the one task being edited
  const archived = sub.status === 'archived'
  const accessLost = useLatest(onAccessLost)
  const inFlight = useRef(new Set()) // synchronous guard against duplicate submissions
  const mutations = useRef(0) // successful changes made here, so an older refresh cannot undo them
  const loadSeq = useRef(0)
  const listRef = useRef(null)
  const previousEditing = useRef(null)

  const load = useCallback(async () => {
    const seq = ++loadSeq.current
    setStatus('loading')
    try {
      const res = await api.subTeamTasks(teamId, sub.sub_team_id)
      if (seq !== loadSeq.current) return
      setTasks(res.data)
      setStatus('done')
    } catch (err) {
      if (seq !== loadSeq.current) return
      if (isResourceGone(err)) accessLost.current?.(err)
      setError(err.message)
      setStatus('error')
    }
  }, [teamId, sub.sub_team_id, accessLost])

  useEffect(() => {
    load()
  }, [load])

  // Re-reads the tasks without a loading flash. The answer is dropped if a newer read started
  // or if a change was made here while it was in flight (it may predate that change).
  const refresh = useCallback(async () => {
    const seq = ++loadSeq.current
    const seen = mutations.current
    try {
      const res = await api.subTeamTasks(teamId, sub.sub_team_id)
      if (seq !== loadSeq.current || seen !== mutations.current) return
      setTasks(res.data)
      setStatus('done')
    } catch (err) {
      if (seq === loadSeq.current && isResourceGone(err)) accessLost.current?.(err)
    }
  }, [teamId, sub.sub_team_id, accessLost])

  // What the server decides about a task depends on the sub-team's roster and status (an
  // assignee who left is unassigned; archiving ends status changes), so a change to either
  // re-reads the tasks. Reopening the tab remounts this component, which also reloads.
  const refreshKey = `${sub.status}|${members.map((m) => m.user_id).join(',')}`
  const lastRefreshKey = useRef(refreshKey)
  useEffect(() => {
    if (lastRefreshKey.current === refreshKey) return
    lastRefreshKey.current = refreshKey
    refresh()
  }, [refreshKey, refresh])

  const isBusy = (key) => Boolean(pending[key])
  const clearFeedback = () => {
    setActionError(null)
    setNotice(null)
  }

  // Runs one action. A second action with the same key while the first is in flight is ignored
  // (returns null), which is what stops duplicate submissions. Resolves to the result, or null.
  const run = async (key, fn, report = setActionError) => {
    if (inFlight.current.has(key)) return null
    inFlight.current.add(key)
    setPending((p) => ({ ...p, [key]: (p[key] || 0) + 1 }))
    try {
      const result = await fn()
      mutations.current += 1
      return result
    } catch (err) {
      if (isResourceGone(err)) accessLost.current?.(err)
      report(err.message)
      return null
    } finally {
      inFlight.current.delete(key)
      setPending((p) => {
        const { [key]: count = 1, ...rest } = p
        return count > 1 ? { ...rest, [key]: count - 1 } : rest
      })
    }
  }

  const replace = (task) => setTasks((list) => list.map((t) => (t.task_id === task.task_id ? task : t)))

  const create = async (event) => {
    event.preventDefault()
    if (!title.trim()) return
    clearFeedback()
    const res = await run('new', () =>
      api.createSubTeamTask(teamId, sub.sub_team_id, { title: title.trim(), assignee_id: assignee || null }),
    )
    if (res) {
      setTasks((list) => [...list, res.data])
      setTitle('')
      setAssignee('')
    }
  }

  const patch = async (task, payload) => {
    clearFeedback()
    const res = await run(task.task_id, () => api.updateSubTeamTask(teamId, sub.sub_team_id, task.task_id, payload))
    if (res) replace(res.data)
  }

  const remove = async (task) => {
    if (!window.confirm(`Delete the task “${task.title}”? This cannot be undone.`)) return
    clearFeedback()
    const res = await run(task.task_id, () => api.deleteSubTeamTask(teamId, sub.sub_team_id, task.task_id))
    if (res) setTasks((list) => list.filter((t) => t.task_id !== task.task_id))
  }

  // --- editing title and description (owner only; the server enforces it) ---------------------------------
  const startEdit = (task) => {
    clearFeedback()
    setEditing({ id: task.task_id, title: task.title || '', description: task.description || '', error: null })
  }
  const closeEdit = () => setEditing(null)
  const setDraft = (field, value) => setEditing((e) => (e ? { ...e, [field]: value, error: null } : e))

  const saveEdit = async (event) => {
    event.preventDefault()
    if (!editing) return
    const task = tasks.find((t) => t.task_id === editing.id)
    if (!task) {
      closeEdit()
      return
    }
    const nextTitle = editing.title.trim()
    const nextDescription = editing.description.trim()
    const fail = (message) => setEditing((e) => (e ? { ...e, error: message } : e))
    if (!nextTitle) return fail('Give the task a title.')
    if (nextTitle.length > MAX_TASK_TITLE) return fail(`The title must be ${MAX_TASK_TITLE} characters or fewer.`)
    if (nextDescription.length > MAX_TASK_DESCRIPTION) {
      return fail(`The description must be ${MAX_TASK_DESCRIPTION} characters or fewer.`)
    }

    // Send only what changed; nothing changed means nothing to save.
    const payload = {}
    if (nextTitle !== task.title) payload.title = nextTitle
    if (nextDescription !== (task.description || '')) payload.description = nextDescription
    if (Object.keys(payload).length === 0) {
      closeEdit()
      return
    }

    clearFeedback()
    // On failure the form stays open with the owner's text, and the task itself is untouched.
    const res = await run(task.task_id, () => api.updateSubTeamTask(teamId, sub.sub_team_id, task.task_id, payload), fail)
    if (res) {
      replace(res.data)
      closeEdit()
      setNotice(`Saved “${res.data.title}”.`)
    }
  }

  // The edit form closes if it can no longer apply: the sub-team was archived, or the task is gone.
  useEffect(() => {
    if (archived) setEditing(null)
  }, [archived])
  const editingId = editing?.id ?? null
  useEffect(() => {
    if (editingId && !tasks.some((t) => t.task_id === editingId)) setEditing(null)
  }, [tasks, editingId])

  // Keyboard users: when the form closes, focus returns to the task's Edit button.
  useEffect(() => {
    if (previousEditing.current && !editingId) {
      listRef.current?.querySelector(`[data-edit-button="${previousEditing.current}"]`)?.focus()
    }
    previousEditing.current = editingId
  }, [editingId])

  // A STABLE ref callback: it runs once when the form opens (focusing the title) and not on later
  // renders, which would pull focus back from the description while the owner types.
  const focusOnMount = useCallback((el) => {
    el?.focus()
  }, [])

  if (status === 'loading') return <Spinner label="Loading tasks…" />
  if (status === 'error') return <ErrorNotice message={error} onRetry={load} />

  const canManage = sub.can_manage && !archived

  return (
    <div>
      {canManage && (
        <form onSubmit={create} className="mb-3 flex flex-wrap gap-2">
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="New task title"
            aria-label="New task title"
            maxLength={MAX_TASK_TITLE}
            className="gm-input min-w-[10rem] flex-1 px-3 py-2 text-sm"
          />
          <select value={assignee} onChange={(e) => setAssignee(e.target.value)} aria-label="Assign new task to" className="gm-input px-2 py-2 text-sm">
            <option value="">Unassigned</option>
            {members.map((m) => (
              <option key={m.user_id} value={m.user_id}>{m.name}</option>
            ))}
          </select>
          <button type="submit" disabled={isBusy('new') || !title.trim()} className="btn-primary t-label-caps px-4 py-2">
            Add task
          </button>
        </form>
      )}
      {actionError && <p className="mb-2" role="alert" style={errorStyle}>{actionError}</p>}
      {notice && <p className="mb-2" role="status" style={{ color: 'var(--primary)', fontSize: 12 }}>{notice}</p>}
      {tasks.length === 0 ? (
        <p className="t-body-md" style={muted}>
          {sub.can_manage ? 'No tasks yet. Add the first one above.' : 'No tasks have been added to this sub-team yet.'}
        </p>
      ) : (
        <ul ref={listRef} className="space-y-2" aria-label="Tasks">
          {tasks.map((t) => {
            const isEditing = editing?.id === t.task_id
            const busy = isBusy(t.task_id)
            return (
              <li key={t.task_id} className="p-3" style={{ border: '1px solid var(--border-technical)', borderRadius: 8 }}>
                {isEditing ? (
                  <form
                    onSubmit={saveEdit}
                    onKeyDown={(e) => {
                      if (e.key === 'Escape' && !busy) {
                        e.stopPropagation()
                        closeEdit()
                      }
                    }}
                    aria-label={`Edit task ${t.title}`}
                    className="space-y-2"
                  >
                    <input
                      value={editing.title}
                      onChange={(e) => setDraft('title', e.target.value)}
                      aria-label="Edit task title"
                      aria-invalid={Boolean(editing.error)}
                      maxLength={MAX_TASK_TITLE}
                      className="gm-input w-full px-3 py-2 text-sm"
                      ref={focusOnMount}
                    />
                    <textarea
                      value={editing.description}
                      onChange={(e) => setDraft('description', e.target.value)}
                      aria-label="Edit task description"
                      placeholder="Description (optional)"
                      maxLength={MAX_TASK_DESCRIPTION}
                      rows={3}
                      className="gm-input w-full px-3 py-2 text-sm"
                    />
                    {editing.error && <p role="alert" style={errorStyle}>{editing.error}</p>}
                    <div className="flex items-center gap-2">
                      <button type="submit" disabled={busy} className="btn-primary t-label-caps px-3 py-1.5" style={{ fontSize: 10 }}>
                        {busy ? 'Saving…' : 'Save'}
                      </button>
                      <button type="button" onClick={closeEdit} disabled={busy} className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>
                        Cancel
                      </button>
                    </div>
                  </form>
                ) : (
                  <>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="t-label-mono" style={{ color: 'var(--on-surface)' }}>{t.title}</p>
                      <div className="flex items-center gap-2">
                        {t.can_update_status ? (
                          <select
                            value={t.status}
                            onChange={(e) => patch(t, { status: e.target.value })}
                            disabled={busy}
                            aria-label={`Status of ${t.title}`}
                            className="gm-input px-2 py-1 text-xs"
                          >
                            {Object.entries(STATUS_LABEL).map(([value, label]) => (
                              <option key={value} value={value}>{label}</option>
                            ))}
                          </select>
                        ) : (
                          <span className="gm-chip px-2 py-0.5">{STATUS_LABEL[t.status]}</span>
                        )}
                        {canManage && (
                          <>
                            <button
                              type="button"
                              data-edit-button={t.task_id}
                              onClick={() => startEdit(t)}
                              disabled={busy}
                              aria-label={`Edit task ${t.title}`}
                              className="t-label-caps"
                              style={{ color: 'var(--primary)', fontSize: 10 }}
                            >
                              Edit
                            </button>
                            <button type="button" onClick={() => remove(t)} disabled={busy} className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>
                              Delete
                            </button>
                          </>
                        )}
                      </div>
                    </div>
                    {t.description && <p className="t-body-md mt-1" style={{ ...muted, fontSize: 12.5 }}>{t.description}</p>}
                  </>
                )}
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  {canManage ? (
                    <select
                      value={t.assignee?.user_id || ''}
                      onChange={(e) => patch(t, { assignee_id: e.target.value || null })}
                      disabled={busy}
                      aria-label={`Assignee of ${t.title}`}
                      className="gm-input px-2 py-1 text-xs"
                    >
                      <option value="">Unassigned</option>
                      {members.map((m) => (
                        <option key={m.user_id} value={m.user_id}>{m.name}</option>
                      ))}
                    </select>
                  ) : (
                    <span className="t-label-mono" style={{ color: 'var(--outline)', fontSize: 11 }}>
                      {t.assignee ? `Assigned to ${t.assignee.user_id === user.user_id ? 'you' : t.assignee.name}` : 'Unassigned'}
                    </span>
                  )}
                  {t.needs_reassignment && (
                    <span className="t-label-mono" style={{ color: '#ffb4ab', fontSize: 11 }}>
                      The person assigned is no longer on this sub-team{sub.can_manage ? ' — reassign it.' : '.'}
                    </span>
                  )}
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

/** Role suggestions for THIS sub-team's roster only. */
function Roles({ teamId, sub, user, onAccessLost }) {
  const [status, setStatus] = useState('idle')
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const accessLost = useLatest(onAccessLost)

  const load = async () => {
    setStatus('loading')
    setError(null)
    try {
      const { data } = await api.subTeamRoles(teamId, sub.sub_team_id)
      setResult(data)
      setStatus('done')
    } catch (err) {
      if (isResourceGone(err)) accessLost.current?.(err)
      setError(err.message)
      setStatus('error')
    }
  }

  return (
    <div>
      <p className="t-body-md mb-3" style={{ ...muted, fontSize: 12.5 }}>
        Advice for the {sub.member_count} {sub.member_count === 1 ? 'person' : 'people'} on this sub-team only. A teammate’s saved profile is used only if they have chosen to share it with teams.
      </p>
      {status === 'idle' && (
        <button type="button" onClick={load} className="btn-secondary t-label-caps px-3 py-2" style={{ fontSize: 10.5 }}>
          Suggest roles for this sub-team
        </button>
      )}
      {status === 'loading' && <Spinner label="Working out roles…" />}
      {status === 'error' && <ErrorNotice message={error} onRetry={load} />}
      {status === 'done' && result && (
        <>
          <RoleFitPanel result={result} userId={user.user_id} teamId={teamId} subTeamId={sub.sub_team_id} />
          <button type="button" onClick={load} className="t-label-caps mt-3" style={{ color: 'var(--outline)', fontSize: 10 }}>
            Refresh
          </button>
        </>
      )}
    </div>
  )
}

/** "Mar 4, 2026, 3:30 PM" - or null when the server sent nothing usable. */
function formatExpiry(iso) {
  const date = iso ? new Date(iso) : null
  if (!date || Number.isNaN(date.getTime())) return null
  return date.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })
}

/** Becomes true when `iso` passes WHILE this is mounted, so a code that runs out with the tab open
 * stops being described as active. The server's `active` flag is what is trusted at load time; the
 * browser clock is never used to decide that an already-listed invitation is expired. */
function useExpiresWhileOpen(iso) {
  const [state, setState] = useState({ iso: null, expired: false })
  useEffect(() => {
    const wait = iso ? new Date(iso).getTime() - Date.now() : NaN
    if (!(wait > 0)) return undefined
    const timer = setTimeout(() => setState({ iso, expired: true }), Math.min(wait + 50, 2_000_000_000))
    return () => clearTimeout(timer)
  }, [iso])
  return state.expired && state.iso === iso
}

/** Roster plus owner-only controls: rename, archive, add/remove members,
 * invitations and deletion. Invitation codes appear once, when created, and live only in this
 * component's state - leaving the tab or closing the panel discards them for good.
 * Every action goes through `act`, which allows one request at a time: each response is a
 * whole-sub-team snapshot, so overlapping ones could otherwise apply out of order. */
function Members({ teamId, sub, parentMembers, onChange, onDeleted, onAccessLost }) {
  const [name, setName] = useState(sub.name)
  const [module, setModule] = useState(sub.module || '')
  const [description, setDescription] = useState(sub.description || '')
  const [pending, setPending] = useState(null) // key of the running action, e.g. "add:bob"
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [code, setCode] = useState(null) // { value, expires_at } - only until this view goes away
  const [copyState, setCopyState] = useState(null) // 'copied' | 'failed'
  const [revokedHere, setRevokedHere] = useState(false)
  const [days, setDays] = useState(7)
  const running = useRef(false)
  const refocus = useRef(null) // what to focus once the running action has finished
  const headingRef = useRef(null)
  const inviteButtonRef = useRef(null)
  const codeRef = useRef(null)
  const memberIds = new Set((sub.members || []).map((m) => m.user_id))
  const addable = parentMembers.filter((m) => !memberIds.has(m.user_id))
  const busy = pending !== null
  const archived = sub.status === 'archived'

  const invite = sub.invite || {}
  const codeExpired = useExpiresWhileOpen(code ? code.expires_at : invite.active ? invite.expires_at : null)
  const inviteActive = Boolean(invite.active) && !codeExpired
  const expiredAt = formatExpiry(invite.expires_at)

  useEffect(() => {
    if (code) codeRef.current?.focus()
  }, [code])

  // Controls are disabled while an action runs, and a disabled control cannot take focus - so focus
  // is placed here, after `pending` has cleared and they are enabled again.
  useEffect(() => {
    if (pending !== null || !refocus.current) return
    const target = refocus.current
    refocus.current = null
    const el = target instanceof Element ? target : target.current
    if (el?.isConnected) el.focus()
  }, [pending])

  const act = async (key, fn, after, trigger) => {
    if (running.current) return null
    running.current = true
    setPending(key)
    setError(null)
    setNotice(null)
    setCopyState(null)
    try {
      const res = await fn()
      after?.(res)
      return res
    } catch (err) {
      setError(err.message)
      // 401/403/404: this view is out of date or access is gone. A 400 on add/remove usually means
      // the person left the parent team meanwhile. Either way, re-read instead of trusting the list.
      if (isAccessLost(err) || (err.status === 400 && /^(add|remove):/.test(key))) onAccessLost?.(err)
      if (trigger) refocus.current = trigger
      return null
    } finally {
      running.current = false
      setPending(null)
    }
  }

  const save = (event) => {
    event.preventDefault()
    return act('settings', () => api.updateSubTeam(teamId, sub.sub_team_id, { name, module, description }), (res) => {
      onChange(res.data)
      setNotice('Saved.')
    })
  }

  const archiveToggle = (event) =>
    act('settings', () => api.updateSubTeam(teamId, sub.sub_team_id, { status: archived ? 'active' : 'archived' }), (res) => onChange(res.data), event.currentTarget)

  const remove = (event) => {
    if (!window.confirm(`Delete “${sub.name}”? Its chat and tasks are deleted too. This cannot be undone.`)) return
    return act('settings', () => api.deleteSubTeam(teamId, sub.sub_team_id), () => onDeleted(), event.currentTarget)
  }

  const addMember = (member, event) =>
    act(`add:${member.user_id}`, () => api.addSubTeamMember(teamId, sub.sub_team_id, member.user_id), (res) => {
      onChange(res.data)
      setNotice(`${member.name} was added.`)
      refocus.current = headingRef // the button that had focus is gone now
    }, event.currentTarget)

  const removeMember = (member, event) => {
    if (!window.confirm(`Remove ${member.name} from “${sub.name}”? Their task assignments here become unassigned and their role choice is cleared.`)) return
    return act(`remove:${member.user_id}`, () => api.removeSubTeamMember(teamId, sub.sub_team_id, member.user_id), (res) => {
      onChange(res.data)
      setNotice(`${member.name} was removed.`)
      refocus.current = headingRef
    }, event.currentTarget)
  }

  const createCode = () =>
    act('invite', () => api.createSubTeamInvite(teamId, sub.sub_team_id, days), (res) => {
      setCode({ value: res.data.invite.code, expires_at: res.data.invite.expires_at })
      setRevokedHere(false)
      onChange({ ...res.data, invite: { ...res.data.invite, code: undefined } })
      setNotice('Invitation code created. Copy it now.')
    })

  const revokeCode = () =>
    act('invite', () => api.revokeSubTeamInvite(teamId, sub.sub_team_id), (res) => {
      setCode(null)
      setRevokedHere(true)
      onChange(res.data)
      setNotice('Invitation revoked. The code no longer works.')
      refocus.current = inviteButtonRef
    })

  const copyCode = async () => {
    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable')
      await navigator.clipboard.writeText(code.value)
      setCopyState('copied')
    } catch {
      setCopyState('failed')
      const el = codeRef.current // leave the code selected so Ctrl+C / long-press works
      if (el && window.getSelection) {
        const range = document.createRange()
        range.selectNodeContents(el)
        const selection = window.getSelection()
        selection.removeAllRanges()
        selection.addRange(range)
        el.focus()
      }
    }
  }

  let inviteText = 'There is no active code.'
  if (inviteActive) inviteText = `The current code expires ${formatExpiry(invite.expires_at) || 'soon'}.`
  else if (invite.expired || codeExpired) inviteText = `There is no active code. The last one expired${expiredAt ? ` on ${expiredAt}` : ''}.`
  else if (revokedHere) inviteText = 'There is no active code. The previous code was revoked.'

  return (
    <div className="min-w-0 space-y-5">
      <section aria-label="Sub-team members">
        <h4 ref={headingRef} tabIndex={-1} className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>Sub-team members ({sub.member_count})</h4>
        {sub.member_count === 0 ? (
          <p className="t-body-md mt-2" style={muted}>No one is on this sub-team yet.</p>
        ) : (
          <ul className="mt-2 space-y-1">
            {sub.members.map((m) => (
              <li key={m.user_id} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-sm">
                <span className="min-w-0 break-words" style={{ color: 'var(--on-surface)' }}>{m.name}</span>
                {sub.can_manage && (
                  <button
                    type="button"
                    disabled={busy}
                    aria-label={`Remove ${m.name} from this sub-team`}
                    onClick={(event) => removeMember(m, event)}
                    className="t-label-caps min-h-9 px-2"
                    style={{ color: 'var(--outline)', fontSize: 10 }}
                  >
                    {pending === `remove:${m.user_id}` ? 'Removing…' : 'Remove'}
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
        <p className="t-label-mono mt-2" style={{ color: 'var(--outline)', fontSize: 11 }}>
          Everyone here is also on the parent team. Removing someone from the parent team removes them from every sub-team.
        </p>
      </section>

      {sub.can_manage && (
        <>
          {addable.length > 0 && (
            <section aria-label="Add parent-team members">
              <h4 className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>Add from the parent team</h4>
              <div className="mt-2 flex flex-wrap gap-2">
                {addable.map((m) => (
                  <button
                    key={m.user_id}
                    type="button"
                    disabled={busy || archived}
                    onClick={(event) => addMember(m, event)}
                    className="gm-chip min-h-9 max-w-full break-words px-2.5 py-1"
                  >
                    {pending === `add:${m.user_id}` ? 'Adding…' : `+ ${m.name}`}
                  </button>
                ))}
              </div>
              {archived && <p className="t-label-mono mt-2" style={{ color: 'var(--outline)', fontSize: 11 }}>Reactivate this sub-team to add people.</p>}
            </section>
          )}

          <form onSubmit={save} className="space-y-2" aria-label="Sub-team settings">
            <h4 className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>Settings</h4>
            <input value={name} onChange={(e) => setName(e.target.value)} maxLength={80} aria-label="Sub-team name" className="gm-input w-full px-3 py-2 text-sm" />
            <input value={module} onChange={(e) => setModule(e.target.value)} maxLength={80} placeholder="Module or workstream" aria-label="Module" className="gm-input w-full px-3 py-2 text-sm" />
            <textarea value={description} onChange={(e) => setDescription(e.target.value)} maxLength={500} rows={2} placeholder="What is this sub-team building?" aria-label="Description" className="gm-input w-full px-3 py-2 text-sm" />
            <div className="flex flex-wrap items-center gap-2">
              <button type="submit" disabled={busy || !name.trim()} className="btn-primary t-label-caps px-3 py-1.5" style={{ fontSize: 10 }}>Save</button>
              <button type="button" disabled={busy} onClick={archiveToggle} className="btn-secondary t-label-caps px-3 py-1.5" style={{ fontSize: 10 }}>
                {archived ? 'Reactivate' : 'Archive'}
              </button>
              <button type="button" disabled={busy} onClick={remove} className="t-label-caps px-3 py-1.5" style={{ color: '#ffb4ab', fontSize: 10 }}>
                Delete sub-team
              </button>
            </div>
          </form>

          <section aria-label="Sub-team invitation">
            <h4 className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>Invitation</h4>
            <p className="t-body-md mt-1" style={{ ...muted, fontSize: 12.5 }}>
              A code lets people who are already on the parent team join this sub-team. It never adds anyone to the parent team.{' '}
              {inviteText}
            </p>
            {code && (
              <div role="group" aria-label="New invitation code" className="mt-2 flex flex-wrap items-center justify-center gap-2 px-3 py-2" style={{ background: 'var(--surface-container-low)', borderRadius: 8 }}>
                <code ref={codeRef} tabIndex={-1} className="t-label-mono min-w-0 select-all break-all tracking-widest" style={{ fontSize: 18 }}>{code.value}</code>
                <button type="button" onClick={copyCode} aria-label="Copy invitation code" className="btn-secondary t-label-caps min-h-9 px-3 py-1.5" style={{ fontSize: 10 }}>
                  Copy
                </button>
              </div>
            )}
            {code && (
              <p className="t-label-mono mt-1" style={{ color: 'var(--outline)', fontSize: 11 }}>
                Copy it now — it is not shown again, and it is lost if you leave this tab or close the panel. Creating a new code stops the old one working.
              </p>
            )}
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <label className="t-label-mono flex items-center gap-1" style={{ fontSize: 11 }}>
                Valid for
                <select value={days} onChange={(e) => setDays(Number(e.target.value))} className="gm-input px-2 py-1 text-xs" aria-label="Invitation validity in days">
                  {[1, 3, 7, 14, 30].map((d) => (
                    <option key={d} value={d}>{d} {d === 1 ? 'day' : 'days'}</option>
                  ))}
                </select>
              </label>
              <button
                ref={inviteButtonRef}
                type="button"
                disabled={busy || archived}
                onClick={createCode}
                className="btn-secondary t-label-caps px-3 py-1.5"
                style={{ fontSize: 10 }}
              >
                {pending === 'invite' ? 'Working…' : inviteActive ? 'Rotate code' : 'Create code'}
              </button>
              {inviteActive && (
                <button type="button" disabled={busy} onClick={revokeCode} className="t-label-caps min-h-9 px-2" style={{ color: 'var(--outline)', fontSize: 10 }}>
                  Revoke
                </button>
              )}
            </div>
            {archived && <p className="t-label-mono mt-2" style={{ color: 'var(--outline)', fontSize: 11 }}>Archived sub-teams cannot be joined. Reactivate it to create a code.</p>}
          </section>
        </>
      )}
      {error && <p role="alert" style={errorStyle}>{error}</p>}
      <p role="status" className="t-label-mono" style={{ color: 'var(--primary)', fontSize: 11 }}>
        {copyState === 'copied' && 'Code copied to the clipboard.'}
        {copyState === 'failed' && 'Could not copy automatically. The code is selected — press Ctrl+C (or copy it by hand).'}
        {!copyState && notice}
      </p>
    </div>
  )
}

/**
 * `rosterKey` changes whenever the parent team's set of members changes (computed by SubTeams);
 * the panel then re-reads the sub-team so member lists, counts and controls are current.
 * `onAccessLost` tells SubTeams to refresh its list when this sub-team stops being reachable.
 */
export default function SubTeamPanel({ team, user, subId, rosterKey, onClose, onChanged, onDeleted, onAccessLost }) {
  const [sub, setSub] = useState(null)
  const [status, setStatus] = useState('loading')
  const [error, setError] = useState(null)
  const [tab, setTab] = useState('chat')
  const [joining, setJoining] = useState(false)
  const [joinError, setJoinError] = useState(null)
  const [endedStatus, setEndedStatus] = useState(null)
  const callbacks = useLatest({ onChanged, onAccessLost })
  const validation = useRef(0) // only the newest read of the sub-team may update the panel

  const load = useCallback(async () => {
    const mine = ++validation.current
    setStatus('loading')
    try {
      const { data } = await api.getSubTeam(team.team_id, subId)
      if (mine !== validation.current) return
      setSub(data)
      setStatus('done')
    } catch (err) {
      if (mine !== validation.current) return
      if (isResourceGone(err)) {
        setEndedStatus(err.status)
        callbacks.current.onAccessLost?.(err)
        return
      }
      setError(err.message)
      setStatus('error')
    }
  }, [team.team_id, subId, callbacks])

  useEffect(() => {
    load()
  }, [load])

  // Re-reads the sub-team without a loading flash. If it can no longer be reached, everything
  // from it is dropped and an explanation is shown; other failures (network, 5xx) change nothing.
  const revalidate = useCallback(async () => {
    const mine = ++validation.current
    try {
      const { data } = await api.getSubTeam(team.team_id, subId)
      if (mine !== validation.current) return
      setSub(data)
      callbacks.current.onChanged?.(data)
    } catch (err) {
      if (mine !== validation.current) return
      if (isResourceGone(err)) {
        setSub(null)
        setEndedStatus(err.status)
        callbacks.current.onAccessLost?.(err)
      }
    }
  }, [team.team_id, subId, callbacks])

  const lastRoster = useRef(rosterKey)
  useEffect(() => {
    if (lastRoster.current === rosterKey) return
    lastRoster.current = rosterKey
    revalidate()
  }, [rosterKey, revalidate])

  const update = (next) => {
    setSub(next)
    onChanged?.(next)
  }

  const joinSelf = async () => {
    if (joining) return
    setJoining(true)
    setJoinError(null)
    try {
      const { data } = await api.addSubTeamMember(team.team_id, subId, user.user_id)
      update(data)
    } catch (err) {
      setJoinError(err.message)
    } finally {
      setJoining(false)
    }
  }

  if (endedStatus) {
    return (
      <section className="glass-panel p-5" style={{ borderRadius: 8 }} aria-label="Sub-team access ended">
        <p className="t-body-md" role="alert" style={muted}>{endedText(endedStatus)}</p>
        <button type="button" onClick={onClose} className="btn-secondary t-label-caps mt-3 px-3 py-1.5" style={{ fontSize: 10.5 }}>
          Close
        </button>
      </section>
    )
  }
  if (status === 'loading') return <Spinner label="Loading sub-team…" />
  if (status === 'error') return <ErrorNotice message={error} onRetry={load} />

  return (
    <section className="glass-panel p-5" style={{ borderRadius: 8 }} aria-label={`Sub-team ${sub.name}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>Sub-team of {team.name}</p>
          <h3 className="t-headline-md" style={{ color: 'var(--primary)', fontSize: 18 }}>{sub.name}</h3>
          {sub.module && <p className="t-label-mono" style={{ color: 'var(--on-surface-variant)', fontSize: 12 }}>Module: {sub.module}</p>}
          {sub.description && <p className="t-body-md mt-1" style={{ ...muted, fontSize: 13 }}>{sub.description}</p>}
          {sub.status === 'archived' && <span className="gm-chip mt-2 inline-block px-2 py-0.5">Archived — read only</span>}
        </div>
        <button type="button" onClick={onClose} className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10.5 }}>Close</button>
      </div>

      <div role="tablist" aria-label="Sub-team sections" className="mt-4 flex flex-wrap gap-1 p-1" style={{ background: 'var(--surface-container-low)', borderRadius: 10 }}>
        {TABS.map((t) => (
          <button
            key={t.key}
            role="tab"
            type="button"
            aria-selected={tab === t.key}
            onClick={() => setTab(t.key)}
            className="t-label-caps px-3 py-1.5"
            style={tab === t.key ? { background: 'var(--primary)', color: 'var(--on-primary)', borderRadius: 8 } : { color: 'var(--on-surface-variant)', borderRadius: 8 }}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="mt-4" role="tabpanel">
        {tab === 'chat' && (
          <Chat
            teamId={team.team_id}
            sub={sub}
            user={user}
            isMember={sub.is_member}
            onJoinSelf={joinSelf}
            joining={joining}
            joinError={joinError}
            onAccessLost={revalidate}
          />
        )}
        {tab === 'tasks' && <Tasks teamId={team.team_id} sub={sub} user={user} members={sub.members || []} onAccessLost={revalidate} />}
        {tab === 'roles' && <Roles teamId={team.team_id} sub={sub} user={user} onAccessLost={revalidate} />}
        {tab === 'members' && (
          <Members teamId={team.team_id} sub={sub} parentMembers={team.members} onChange={update} onDeleted={() => onDeleted?.(sub.sub_team_id)} onAccessLost={revalidate} />
        )}
      </div>
    </section>
  )
}
