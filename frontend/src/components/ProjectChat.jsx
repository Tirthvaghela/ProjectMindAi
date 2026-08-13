import { useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import api from '../services/api'
import MarkdownLite from './MarkdownLite'
import Panel from './Panel'

const STARTERS = [
  'What should I build first?',
  'Explain the architecture in simple terms.',
  'What could go wrong, and how do I avoid it?',
]

// Unlike the full-page Chat, this widget has no server-side conversation to
// reload from — /project/<id>/chat is stateless (see routes/assistant.py) —
// so "persisted history" here means the browser remembers it, keyed per
// project so switching projects doesn't bleed one conversation into another.
function storageKey(projectId) {
  return `projectmind.chat.${projectId}`
}

function loadSavedMessages(projectId) {
  try {
    const raw = localStorage.getItem(storageKey(projectId))
    const parsed = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

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
      className="shrink-0 self-end p-1 opacity-0 transition group-hover:opacity-100 hover:bg-white/10"
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
      <div className={`flex max-w-[85%] items-end gap-1 ${isUser ? 'flex-row-reverse' : ''}`}>
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

/**
 * Project-grounded chat, backed by an external LLM (see backend/nlp/ai_assistant.py).
 *
 * Availability is checked once against /api/health rather than discovered by
 * letting a user's first message fail — a deployment without GROQ_API_KEY set
 * simply never shows this panel, instead of showing an input box that always
 * errors.
 */
export default function ProjectChat({ projectId }) {
  const [available, setAvailable] = useState(null)
  const [messages, setMessages] = useState(() => loadSavedMessages(projectId))
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const bottomRef = useRef(null)

  useEffect(() => {
    api
      .health()
      .then((data) => setAvailable(Boolean(data?.ai_assistant?.enabled)))
      .catch(() => setAvailable(false))
  }, [])

  // Re-load whenever the project changes — this component doesn't remount
  // across a client-side navigation between two ProjectDetail pages.
  useEffect(() => {
    setMessages(loadSavedMessages(projectId))
  }, [projectId])

  useEffect(() => {
    try {
      if (messages.length > 0) {
        localStorage.setItem(storageKey(projectId), JSON.stringify(messages))
      } else {
        localStorage.removeItem(storageKey(projectId))
      }
    } catch {
      /* private mode, quota, storage disabled — the chat still works this session */
    }
  }, [messages, projectId])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [messages, busy])

  const send = async (text = input) => {
    const message = text.trim()
    if (!message || busy) return

    const history = messages.map(({ role, content }) => ({ role, content }))
    setMessages((m) => [...m, { role: 'user', content: message }])
    setInput('')
    setBusy(true)
    setError(null)

    try {
      const { data } = await api.chat(projectId, message, history)
      setMessages((m) => [...m, { role: 'assistant', content: data.reply }])
    } catch (err) {
      setError(err.message)
      // Roll back the optimistic message so retrying doesn't duplicate it.
      setMessages((m) => m.slice(0, -1))
    } finally {
      setBusy(false)
    }
  }

  if (!available) return null

  return (
    <Panel
      icon="smart_toy"
      title="Ask about this project"
      description="A mentor that knows this project's details — architecture, technologies, what to build first."
      actions={
        messages.length > 0 && (
          <button
            onClick={() => setMessages([])}
            className="t-label-mono shrink-0 px-2.5 py-1.5 transition hover:opacity-80"
            style={{ border: '1px solid var(--border-technical)', color: 'var(--on-surface-variant)', fontSize: 12, borderRadius: 8 }}
          >
            New chat
          </button>
        )
      }
    >
      {messages.length === 0 ? (
        <div className="flex flex-wrap gap-2">
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
      ) : (
        <div className="max-h-[32rem] space-y-2.5 overflow-y-auto pr-1">
          {messages.map((m, i) => (
            <Bubble key={i} role={m.role} content={m.content} />
          ))}
          {busy && <TypingDots />}
          <div ref={bottomRef} />
        </div>
      )}

      {error && <p className="t-body-md mt-2" style={{ color: '#ffb4ab', fontSize: 12 }}>{error}</p>}

      <form
        onSubmit={(e) => {
          e.preventDefault()
          send()
        }}
        className="mt-4 flex gap-2"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask a question about this project…"
          aria-label="Ask about this project"
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
    </Panel>
  )
}
