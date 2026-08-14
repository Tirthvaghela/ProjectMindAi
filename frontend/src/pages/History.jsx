import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import api from '../services/api'
import PageHeader from '../components/PageHeader'
import { Spinner, ErrorNotice, EmptyState } from '../components/Feedback'
import { formatRelative } from '../utils/time'

export default function History() {
  const [entries, setEntries] = useState([])
  const [status, setStatus] = useState('loading')
  const [error, setError] = useState(null)
  const [confirmingClear, setConfirmingClear] = useState(false)
  const [clearError, setClearError] = useState(null)
  const [clearing, setClearing] = useState(false)

  const load = () => {
    setStatus('loading')
    api
      .history(30)
      .then((res) => {
        setEntries(res.data)
        setStatus('done')
      })
      .catch((err) => {
        setError(err.message)
        setStatus('error')
      })
  }

  useEffect(load, [])

  const clear = async () => {
    setClearing(true)
    setClearError(null)
    try {
      await api.clearHistory()
      setEntries([])
      setConfirmingClear(false)
    } catch (err) {
      setClearError(err.message)
    } finally {
      setClearing(false)
    }
  }

  if (status === 'loading') return <div className="mx-auto max-w-6xl px-6 py-14"><Spinner label="Loading history…" /></div>
  if (status === 'error') return <div className="mx-auto max-w-6xl px-6 py-14"><ErrorNotice message={error} onRetry={load} /></div>

  return (
    <div className="mx-auto max-w-6xl px-6 py-14">
      <PageHeader
        title="Search history"
        description="Your recent searches. Select one to run it again."
        actions={
          entries.length > 0 &&
          (confirmingClear ? (
            <div className="flex items-center gap-2">
              <span className="t-label-mono" style={{ color: 'var(--on-surface-variant)', fontSize: 12 }}>
                Clear all history?
              </span>
              <button
                onClick={clear}
                disabled={clearing}
                className="t-label-caps px-3 py-1.5 transition hover:opacity-80 disabled:opacity-60"
                style={{ border: '1px solid rgba(255,180,171,0.3)', color: '#ffb4ab', borderRadius: 8 }}
              >
                {clearing ? 'Clearing…' : 'Confirm'}
              </button>
              <button
                onClick={() => {
                  setConfirmingClear(false)
                  setClearError(null)
                }}
                disabled={clearing}
                className="t-label-caps px-3 py-1.5 transition hover:opacity-80 disabled:opacity-60"
                style={{ border: '1px solid var(--border-technical)', color: 'var(--on-surface-variant)', borderRadius: 8 }}
              >
                Cancel
              </button>
            </div>
          ) : (
            <button
              onClick={() => setConfirmingClear(true)}
              className="t-label-caps px-3 py-1.5 transition hover:opacity-80"
              style={{ border: '1px solid rgba(255,180,171,0.3)', color: '#ffb4ab', borderRadius: 8 }}
            >
              Clear all
            </button>
          ))
        }
      />

      {clearError && (
        <p className="t-body-md mb-6" style={{ color: '#ffb4ab', fontSize: 13 }}>
          Could not clear history: {clearError}
        </p>
      )}

      {entries.length === 0 ? (
        <EmptyState title="No searches yet" hint="Your recent searches will appear here." />
      ) : (
        <ul className="glass-panel overflow-hidden" style={{ borderRadius: 8 }}>
          {entries.map((entry, index) => (
            <li key={`${entry.query}-${entry.created_at}-${index}`} style={{ borderTop: index > 0 ? '1px solid var(--border-technical)' : 'none' }}>
              <Link
                to={`/?q=${encodeURIComponent(entry.query)}`}
                className="flex items-center justify-between gap-4 px-4 py-3 transition hover:bg-white/5"
              >
                <div className="min-w-0">
                  <p className="t-label-mono truncate" style={{ color: 'var(--on-surface)' }}>{entry.query}</p>
                  <p className="t-body-md mt-0.5" style={{ color: 'var(--on-surface-variant)', fontSize: 12.5 }}>
                    {entry.result_count} result{entry.result_count === 1 ? '' : 's'}
                    {Object.keys(entry.filters ?? {}).length > 0 &&
                      ` · filtered by ${Object.keys(entry.filters).join(', ')}`}
                  </p>
                </div>
                <span className="t-label-mono shrink-0" style={{ color: 'var(--outline)', fontSize: 11 }}>{formatRelative(entry.created_at)}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
