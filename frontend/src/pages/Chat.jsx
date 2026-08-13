import { useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import api from '../services/api'
import MarkdownLite from '../components/MarkdownLite'
import { Spinner, EmptyState } from '../components/Feedback'
import { formatRelative } from '../utils/time'

const STARTERS = [
  'Give me three beginner-friendly NLP project ideas.',
  'Explain the difference between a REST API and GraphQL.',
  'How do I structure a README for a student project?',
]

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text)
          setCopied(true)
          setTimeout(() => setCopied(false), 1500)
        } catch {
          /* Clipboard API unavailable (insecure context, permissions) — not worth surfacing. */
        }
      }}
      className="p-1 opacity-0 transition group-hover:opacity-100 hover:bg-white/10"
      style={{ color: 'var(--outline)', borderRadius: 6 }}
      aria-label="Copy message"
      title={copied ? 'Copied' : 'Copy'}
    >
      {copied ? (
        <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
        </svg>
      ) : (
        <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
          <rect x="9" y="9" width="11" height="11" rx="2" />
          <path d="M5 15V5a2 2 0 012-2h10" />
        </svg>
      )}
    </button>
  )
}

function Bubble({ role, content }) {
  const isUser = role === 'user'
  return (
    <div className={`group flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div className={`flex max-w-[85%] items-end gap-1.5 ${isUser ? 'flex-row-reverse' : ''}`}>
        <div
          className="px-3.5 py-2.5 text-sm leading-relaxed"
          style={
            isUser
              ? { whiteSpace: 'pre-wrap', background: 'var(--primary)', color: 'var(--on-primary)', borderRadius: 8 }
              : { background: 'var(--surface-container-low)', color: 'var(--on-surface-variant)', border: '1px solid var(--border-technical)', borderRadius: 8 }
          }
        >
          {isUser ? content : <MarkdownLite content={content} />}
        </div>
        {!isUser && <CopyButton text={content} />}
      </div>
    </div>
  )
}

function TypingDots() {
  return (
    <div className="flex w-fit items-center gap-1 px-3.5 py-3" style={{ background: 'var(--surface-container-low)', border: '1px solid var(--border-technical)', borderRadius: 8 }}>
      {[0, 1, 2].map((i) => (
        <motion.span
          key={i}
          className="h-1.5 w-1.5 rounded-full"
          style={{ background: 'var(--outline)' }}
          animate={{ opacity: [0.3, 1, 0.3] }}
          transition={{ duration: 1, repeat: Infinity, delay: i * 0.15 }}
        />
      ))}
    </div>
  )
}

function ConversationList({ conversations, activeId, onSelect, onDelete }) {
  if (conversations.length === 0) {
    return <p className="t-body-md px-3 py-6 text-center" style={{ color: 'var(--outline)', fontSize: 12.5 }}>No conversations yet.</p>
  }
  return (
    <ul className="space-y-0.5 overflow-y-auto px-2 py-2">
      {conversations.map((c) => (
        <li key={c.conversation_id} className="group relative">
          <button
            onClick={() => onSelect(c.conversation_id)}
            className="block w-full truncate px-3 py-2 pr-8 text-left text-sm transition hover:bg-white/5"
            style={
              c.conversation_id === activeId
                ? { background: 'var(--surface-container-high)', color: 'var(--on-surface)', borderRadius: 8 }
                : { color: 'var(--on-surface-variant)', borderRadius: 8 }
            }
          >
            {c.title}
            <span className="t-label-mono block truncate" style={{ color: 'var(--outline)', fontSize: 11 }}>
              {formatRelative(c.updated_at)}
            </span>
          </button>
          <button
            onClick={(e) => {
              e.stopPropagation()
              onDelete(c.conversation_id)
            }}
            aria-label={`Delete "${c.title}"`}
            className="absolute right-1.5 top-1.5 p-1 opacity-0 transition hover:bg-white/10 group-hover:opacity-100"
            style={{ color: 'var(--outline)', borderRadius: 6 }}
          >
            <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 7h12M9 7V5a1 1 0 011-1h4a1 1 0 011 1v2m2 0l-.7 12.1a1 1 0 01-1 .9H7.7a1 1 0 01-1-.9L6 7h12z" />
            </svg>
          </button>
        </li>
      ))}
    </ul>
  )
}

/**
 * Standalone ChatGPT-style page: a sidebar of saved conversations plus a
 * message pane, backed by the same Groq assistant as ProjectChat but with no
 * project in scope (see backend/nlp/ai_assistant.py:general_reply). Unlike
 * ProjectChat this one persists on the server — conversation_id, keyed to
 * the anonymous X-Device-Id, is what lets the sidebar list survive a reload.
 */
export default function Chat() {
  const [available, setAvailable] = useState(null)
  const [conversations, setConversations] = useState([])
  const [activeId, setActiveId] = useState(null)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loadingList, setLoadingList] = useState(true)
  const [loadingConversation, setLoadingConversation] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const bottomRef = useRef(null)

  useEffect(() => {
    api
      .health()
      .then((data) => setAvailable(Boolean(data?.ai_assistant?.enabled)))
      .catch(() => setAvailable(false))
  }, [])

  const loadConversations = () => {
    setLoadingList(true)
    return api
      .listConversations()
      .then((res) => setConversations(res.data))
      .catch(() => setConversations([]))
      .finally(() => setLoadingList(false))
  }

  useEffect(() => {
    if (available) loadConversations()
  }, [available])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [messages, busy])

  const openConversation = async (id) => {
    setActiveId(id)
    setError(null)
    setLoadingConversation(true)
    try {
      const { data } = await api.getConversation(id)
      setMessages(data.messages)
    } catch (err) {
      setError(err.message)
      setMessages([])
    } finally {
      setLoadingConversation(false)
    }
  }

  const startNewChat = () => {
    setActiveId(null)
    setMessages([])
    setError(null)
    setInput('')
  }

  const deleteConversation = async (id) => {
    if (!window.confirm('Delete this conversation? This cannot be undone.')) return
    try {
      await api.deleteConversation(id)
      setConversations((cs) => cs.filter((c) => c.conversation_id !== id))
      if (id === activeId) startNewChat()
    } catch (err) {
      setError(err.message)
    }
  }

  const send = async (text = input) => {
    const message = text.trim()
    if (!message || busy) return

    setInput('')
    setBusy(true)
    setError(null)
    setMessages((m) => [...m, { role: 'user', content: message }])

    try {
      let conversationId = activeId
      if (!conversationId) {
        const { data } = await api.createConversation()
        conversationId = data.conversation_id
        setActiveId(conversationId)
      }

      const { data } = await api.sendConversationMessage(conversationId, message)
      setMessages((m) => [...m, { role: 'assistant', content: data.reply }])
      loadConversations()
    } catch (err) {
      setError(err.message)
      setMessages((m) => m.slice(0, -1))
    } finally {
      setBusy(false)
    }
  }

  if (available === null) return <div className="mx-auto max-w-6xl px-6 py-14"><Spinner label="Checking assistant availability…" /></div>

  if (!available) {
    return (
      <div className="mx-auto max-w-6xl px-6 py-14">
        <EmptyState
          title="AI chat isn't configured"
          hint="Set GROQ_API_KEY in backend/.env to enable the assistant, then reload this page."
        />
      </div>
    )
  }

  return (
    <div className="mx-auto grid h-[75vh] min-h-[32rem] max-w-6xl gap-4 px-6 py-14 lg:grid-cols-[260px_1fr]">
      <aside className="glass-panel flex flex-col overflow-hidden" style={{ borderRadius: 8 }}>
        <div className="p-2.5">
          <button
            onClick={startNewChat}
            className="btn-secondary flex w-full items-center justify-center gap-1.5 px-3 py-2 text-sm"
          >
            <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 5v14M5 12h14" />
            </svg>
            New chat
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto" style={{ borderTop: '1px solid var(--border-technical)' }}>
          {loadingList ? (
            <p className="t-body-md px-3 py-6 text-center" style={{ color: 'var(--outline)', fontSize: 12.5 }}>Loading…</p>
          ) : (
            <ConversationList
              conversations={conversations}
              activeId={activeId}
              onSelect={openConversation}
              onDelete={deleteConversation}
            />
          )}
        </div>
      </aside>

      <section className="glass-panel flex min-h-0 flex-col" style={{ borderRadius: 8 }}>
        <div className="px-5 py-4" style={{ borderBottom: '1px solid var(--border-technical)' }}>
          <h1 className="t-label-mono" style={{ color: 'var(--primary)', fontSize: 15 }}>ProjectMind Assistant</h1>
          <p className="t-body-md" style={{ color: 'var(--on-surface-variant)', fontSize: 13 }}>
            Ask anything about building your project — ideas, architecture, debugging, concepts.
          </p>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {loadingConversation ? (
            <Spinner label="Loading conversation…" />
          ) : messages.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
              <p className="t-body-md" style={{ color: 'var(--outline)', fontSize: 13 }}>Start a conversation, or try one of these:</p>
              <div className="flex max-w-md flex-wrap justify-center gap-2">
                {STARTERS.map((q) => (
                  <button
                    key={q}
                    onClick={() => send(q)}
                    className="t-label-mono px-3 py-1.5 transition hover:opacity-80"
                    style={{ border: '1px solid var(--border-technical)', color: 'var(--on-surface-variant)', fontSize: 12, borderRadius: 999 }}
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              {messages.map((m, i) => (
                <Bubble key={i} role={m.role} content={m.content} />
              ))}
              {busy && <TypingDots />}
              <div ref={bottomRef} />
            </div>
          )}
        </div>

        {error && <p className="t-body-md px-5" style={{ color: '#ffb4ab', fontSize: 12 }}>{error}</p>}

        <form
          onSubmit={(e) => {
            e.preventDefault()
            send()
          }}
          className="flex gap-2 p-3"
          style={{ borderTop: '1px solid var(--border-technical)' }}
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Message the assistant…"
            aria-label="Message the assistant"
            className="gm-input flex-1 px-3 py-2 text-sm"
          />
          <button
            type="submit"
            disabled={busy || !input.trim()}
            className="btn-primary t-label-caps shrink-0 px-4 py-2"
          >
            Send
          </button>
        </form>
      </section>
    </div>
  )
}
