import { useState } from 'react'
import { motion } from 'framer-motion'

/**
 * Copy-to-clipboard button for one chat bubble — previously duplicated
 * byte-for-byte between Dashboard.jsx (the full-page assistant thread) and
 * ProjectChat.jsx (the per-project/idea widget); pulled out here so the two
 * copies can't drift. `label` only changes the accessible name/tooltip verb
 * ("response" vs "message") to match each caller's own wording.
 */
export function CopyButton({ text, label = 'response' }) {
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
      aria-label={`Copy ${label}`}
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

/** Three-dot "the assistant is typing" indicator — same duplication/fix as
 * CopyButton above, identical in both places it existed. */
export function TypingDots() {
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
