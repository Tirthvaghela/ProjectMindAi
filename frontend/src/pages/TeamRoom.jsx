import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { motion } from 'framer-motion'
import useAuth from '../hooks/useAuth.jsx'
import useVoiceSearch from '../hooks/useVoiceSearch'
import api from '../services/api'
import MarkdownLite from '../components/MarkdownLite'
import { Spinner, ErrorNotice, EmptyState } from '../components/Feedback'
import Panel from '../components/Panel'
import { formatClockTime, formatDate } from '../utils/time'

/**
 * WhatsApp-shaped: your messages on the right in a solid bubble, everyone
 * else's on the left with an avatar and their name inside the bubble. In a
 * team room with 3+ members "left" isn't one fixed person the way it is in
 * a 1:1 chat, so each incoming bubble carries its sender's name — the
 * avatar alone wouldn't disambiguate a group. Markdown-rendered like every
 * other AI-facing bubble in this app (MarkdownLite is safe by construction:
 * no dangerouslySetInnerHTML, see its own header comment) since these are
 * real teammates who might paste code or a link.
 */
function MessageRow({ message, mine }) {
  return (
    <div className={`flex gap-2 px-2 py-1 ${mine ? 'justify-end' : 'justify-start'}`}>
      {!mine && (
        <div
          className="grid h-7 w-7 shrink-0 place-items-center self-end rounded-full"
          style={{ background: 'var(--surface-container-highest)', color: 'var(--on-surface-variant)', border: '1px solid var(--border-technical)' }}
        >
          <span className="t-label-mono" style={{ fontSize: 11 }}>
            {message.author_name.charAt(0).toUpperCase()}
          </span>
        </div>
      )}
      <div className={`flex max-w-[70%] flex-col ${mine ? 'items-end' : 'items-start'}`}>
        <div
          className="px-3.5 py-2.5 text-sm leading-relaxed"
          style={
            mine
              ? { background: 'var(--primary)', color: 'var(--on-primary)', borderRadius: '10px 10px 2px 10px' }
              : { background: 'var(--surface-container-low)', border: '1px solid var(--border-technical)', color: 'var(--on-surface-variant)', borderRadius: '10px 10px 10px 2px' }
          }
        >
          {!mine && (
            <p className="t-label-mono mb-1" style={{ color: 'var(--primary)', fontSize: 12 }}>
              {message.author_name}
            </p>
          )}
          <MarkdownLite content={message.content} />
        </div>
        <span className="t-label-mono mt-1 px-1" style={{ color: 'var(--outline)', fontSize: 10.5 }}>
          {formatClockTime(message.created_at)}
        </span>
      </div>
    </div>
  )
}

/**
 * Polls for new messages every 4s rather than a websocket connection — see
 * backend/teams/service.py for why: a handful of people, infrequent
 * messages, and it keeps this deployment's story identical to the rest of
 * the app (no separate real-time infra to run).
 */
export default function TeamRoom() {
  const { id } = useParams()
  const { user, loading: authLoading } = useAuth()
  const [team, setTeam] = useState(null)
  const [project, setProject] = useState(null)
  const [messages, setMessages] = useState([])
  const [status, setStatus] = useState('loading')
  const [error, setError] = useState(null)
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const bottomRef = useRef(null)
  const stickToBottom = useRef(true)
  const { supported: voiceSupported, listening, start, stop } = useVoiceSearch()

  // Team rooms are account-only, same as the Teams list (backend/routes/
  // teams.py requires current_user() on every route) — without this guard a
  // signed-out visit still fired the fetch, got a raw 401 back, and showed
  // a generic "Sign in required." error box instead of the same deliberate
  // sign-in prompt Teams.jsx shows. Skipping the fetch entirely here also
  // means `user.user_id` below is never reached while `user` is null.
  useEffect(() => {
    if (authLoading || !user) return
    let cancelled = false
    setStatus('loading')

    Promise.all([api.getTeam(id), api.teamMessages(id)])
      .then(([teamRes, messagesRes]) => {
        if (cancelled) return
        setTeam(teamRes.data)
        setMessages(messagesRes.data)
        setStatus('done')
        // Secondary — the room still works even if this fails, it just
        // won't show the project's domain/tech-stack chips in the sidebar.
        api.getProject(teamRes.data.project_id).then(({ data }) => {
          if (!cancelled) setProject(data)
        }).catch(() => {})
      })
      .catch((err) => {
        if (cancelled) return
        setError(err.message)
        setStatus('error')
      })

    return () => {
      cancelled = true
    }
  }, [id, user, authLoading])

  useEffect(() => {
    if (status !== 'done') return
    const interval = setInterval(() => {
      api
        .teamMessages(id)
        .then((res) => setMessages(res.data))
        .catch(() => {
          /* A missed poll just tries again in 4s — no need to surface it. */
        })
    }, 4000)
    return () => clearInterval(interval)
  }, [id, status])

  useEffect(() => {
    if (stickToBottom.current) bottomRef.current?.scrollIntoView({ block: 'nearest' })
  }, [messages])

  const send = async (event) => {
    event.preventDefault()
    const content = draft.trim()
    if (!content || sending) return
    setSending(true)
    try {
      const { data } = await api.postTeamMessage(id, content)
      setMessages((m) => [...m, data])
      setDraft('')
    } catch (err) {
      setError(err.message)
    } finally {
      setSending(false)
    }
  }

  if (authLoading) return <div className="mx-auto max-w-6xl px-6 py-14"><Spinner /></div>

  if (!user) {
    return (
      <div className="mx-auto max-w-6xl px-6 py-14">
        <EmptyState title="Sign in to view this team" hint="Team workspaces are the one part of this app that needs an account.">
          <Link to="/account" className="btn-primary t-label-caps inline-block px-4 py-2">
            Sign in
          </Link>
        </EmptyState>
      </div>
    )
  }

  if (status === 'loading') return <div className="mx-auto max-w-6xl px-6 py-14"><Spinner label="Loading team…" /></div>
  if (status === 'error') return <div className="mx-auto max-w-6xl px-6 py-14"><ErrorNotice message={error} /></div>

  return (
    <div className="mx-auto max-w-6xl space-y-6 px-6 py-14">
      <Link
        to="/teams"
        className="t-label-mono inline-flex items-center gap-1.5 transition hover:opacity-75"
        style={{ color: 'var(--on-surface-variant)' }}
      >
        <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
        </svg>
        All teams
      </Link>

      <div className="grid gap-6 lg:grid-cols-[1fr_280px]">
        <section className="glass-panel flex h-[38rem] flex-col" style={{ borderRadius: 8 }}>
          <div className="px-5 py-4" style={{ borderBottom: '1px solid var(--border-technical)' }}>
            <h1 className="t-label-mono" style={{ color: 'var(--primary)', fontSize: 16 }}>
              # {team.name}
            </h1>
            <p className="t-label-mono mt-0.5" style={{ color: 'var(--outline)', fontSize: 11 }}>
              {team.members.length} member{team.members.length === 1 ? '' : 's'} ·{' '}
              <Link to={`/project/${team.project_id}`} className="transition hover:opacity-75" style={{ color: 'var(--on-surface-variant)' }}>
                {team.project_title}
              </Link>
            </p>
          </div>

          <div
            className="flex-1 space-y-1 overflow-y-auto px-3 py-4"
            onScroll={(e) => {
              const el = e.currentTarget
              stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60
            }}
          >
            {messages.length === 0 ? (
              <p className="t-body-md py-8 text-center" style={{ color: 'var(--outline)', fontSize: 13 }}>No messages yet — say hello.</p>
            ) : (
              messages.map((m) => <MessageRow key={m.message_id} message={m} mine={m.user_id === user.user_id} />)
            )}
            <div ref={bottomRef} />
          </div>

          <form onSubmit={send} className="flex flex-col gap-1.5 p-3" style={{ borderTop: '1px solid var(--border-technical)' }}>
            <div className="flex gap-2">
              <input
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder="Message your team…"
                aria-label="Message your team"
                className="gm-input flex-1 px-3 py-2 text-sm"
              />
              {voiceSupported && (
                <button
                  type="button"
                  onClick={() => (listening ? stop() : start(setDraft))}
                  aria-label={listening ? 'Stop voice input' : 'Message by voice'}
                  aria-pressed={listening}
                  className="grid h-9 w-9 shrink-0 place-items-center transition hover:bg-white/10"
                  style={{ color: listening ? 'var(--primary)' : 'var(--outline)', border: '1px solid var(--border-technical)', borderRadius: 6 }}
                >
                  <span className="material-symbols-outlined" style={{ fontSize: 18 }}>
                    mic
                  </span>
                </button>
              )}
              <button
                type="submit"
                disabled={sending || !draft.trim()}
                className="btn-primary t-label-caps shrink-0 px-4 py-2"
              >
                Send
              </button>
            </div>
            <p className="t-label-mono px-1" style={{ color: 'var(--outline)', fontSize: 10 }}>
              Markdown supported
            </p>
          </form>
        </section>

        <aside className="space-y-4">
          <Panel icon="groups" title={`Members (${team.members.length})`} compact>
            <ul className="space-y-2">
              {team.members.map((m) => (
                <motion.li key={m.user_id} initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex items-center gap-2 text-sm">
                  <span
                    className="t-label-mono grid h-6 w-6 shrink-0 place-items-center rounded-full"
                    style={{ background: 'var(--surface-container-highest)', color: 'var(--on-surface)', fontSize: 11 }}
                  >
                    {m.name.charAt(0).toUpperCase()}
                  </span>
                  <span className="t-body-md" style={{ color: 'var(--on-surface-variant)' }}>
                    {m.name}
                    {m.user_id === team.owner_user_id && (
                      <span className="t-label-mono ml-1.5" style={{ color: 'var(--outline)', fontSize: 11 }}>(owner)</span>
                    )}
                  </span>
                </motion.li>
              ))}
            </ul>
          </Panel>

          <Panel icon="folder_open" title="Project" compact>
            <Link to={`/project/${team.project_id}`} className="block transition hover:opacity-80">
              <p className="t-label-mono" style={{ color: 'var(--primary)', fontSize: 13 }}>
                {team.project_title}
              </p>
            </Link>
            {project && (
              <>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  <span className="gm-chip px-2 py-0.5">{project.domain}</span>
                  <span className="gm-chip px-2 py-0.5">{project.difficulty}</span>
                </div>
                {project.technologies?.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {project.technologies.slice(0, 4).map((t) => (
                      <span
                        key={t}
                        className="t-label-mono px-1.5 py-0.5"
                        style={{ border: '1px solid var(--border-technical)', color: 'var(--on-surface-variant)', fontSize: 10, borderRadius: 4 }}
                      >
                        {t}
                      </span>
                    ))}
                  </div>
                )}
              </>
            )}
          </Panel>

          <Panel icon="key" title="Invite code" compact>
            <p
              className="t-label-mono px-3 py-2 text-center tracking-widest"
              style={{ background: 'var(--surface-container-low)', color: 'var(--on-surface)', fontSize: 18, borderRadius: 8 }}
            >
              {team.invite_code}
            </p>
            <p className="t-label-mono mt-2" style={{ color: 'var(--outline)', fontSize: 11 }}>
              Share this with teammates so they can join. Formed {formatDate(team.created_at)}.
            </p>
          </Panel>
        </aside>
      </div>
    </div>
  )
}
