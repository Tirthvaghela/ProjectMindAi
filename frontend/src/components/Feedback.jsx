import { motion } from 'framer-motion'

export function Spinner({ label = 'Loading…' }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-20">
      <div
        className="h-8 w-8 animate-spin rounded-full border-2"
        style={{ borderColor: 'var(--border-technical)', borderTopColor: 'var(--primary)' }}
      />
      <p className="t-label-mono" style={{ color: 'var(--on-surface-variant)' }}>{label}</p>
    </div>
  )
}

export function ErrorNotice({ message, onRetry }) {
  return (
    <div
      className="flex gap-3 p-5"
      style={{ border: '1px solid rgba(255,180,171,0.3)', background: 'rgba(255,180,171,0.06)', borderRadius: 8 }}
    >
      <svg
        className="mt-0.5 h-5 w-5 shrink-0"
        style={{ color: '#ffb4ab' }}
        fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"
      >
        <circle cx="12" cy="12" r="9" />
        <path strokeLinecap="round" d="M12 8v5M12 16.5v.01" />
      </svg>
      <div className="min-w-0">
        <p className="t-label-mono font-semibold" style={{ color: '#ffb4ab' }}>Something went wrong</p>
        <p className="t-body-md mt-1" style={{ color: 'var(--on-surface-variant)' }}>{message}</p>
        {onRetry && (
          <button
            onClick={onRetry}
            className="t-label-caps mt-3 px-3.5 py-1.5 transition hover:opacity-85"
            style={{ background: 'var(--primary)', color: 'var(--on-primary)', borderRadius: 8 }}
          >
            Try again
          </button>
        )}
      </div>
    </div>
  )
}

export function EmptyState({ title, hint, children }) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="py-16 text-center"
      style={{ border: '1px dashed var(--border-technical)', borderRadius: 8 }}
    >
      <div
        className="mx-auto grid h-11 w-11 place-items-center rounded-full"
        style={{ border: '1px solid var(--border-technical)', color: 'var(--outline)' }}
      >
        <svg className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
          <circle cx="11" cy="11" r="7" />
          <path strokeLinecap="round" d="M21 21l-4.3-4.3" />
        </svg>
      </div>
      <p className="t-label-mono mt-3" style={{ color: 'var(--on-surface)' }}>{title}</p>
      {hint && (
        <p className="t-body-md mx-auto mt-1.5 max-w-md" style={{ color: 'var(--on-surface-variant)' }}>
          {hint}
        </p>
      )}
      {children && <div className="mt-5">{children}</div>}
    </motion.div>
  )
}
