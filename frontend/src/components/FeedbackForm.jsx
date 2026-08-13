import { useState } from 'react'
import { motion } from 'framer-motion'
import api from '../services/api'
import Panel from './Panel'

/**
 * Relevance feedback.
 *
 * The backend has accepted feedback since the first version; this is the UI
 * that finally reaches it. `POST /api/feedback` requires a rating OR a
 * message, so the submit button stays disabled until one of them exists rather
 * than letting the user discover that rule as a 400.
 *
 * `projectId` and `query` are optional context — passing them is what turns
 * free-text feedback into labelled data the evaluation script can use.
 */
export default function FeedbackForm({
  projectId = null,
  query = null,
  title = 'Was this useful?',
  hint = 'Ratings and comments help tune the ranking.',
}) {
  const [rating, setRating] = useState(0)
  const [message, setMessage] = useState('')
  const [status, setStatus] = useState('idle')
  const [error, setError] = useState(null)

  const canSubmit = rating > 0 || message.trim().length > 0

  const submit = async (event) => {
    event.preventDefault()
    if (!canSubmit || status === 'sending') return

    setStatus('sending')
    setError(null)
    try {
      await api.feedback({
        rating: rating || undefined,
        message: message.trim() || undefined,
        project_id: projectId || undefined,
        query: query || undefined,
      })
      setStatus('sent')
    } catch (err) {
      setError(err.message)
      setStatus('idle')
    }
  }

  if (status === 'sent') {
    return (
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        className="flex items-center gap-2.5 p-4 text-sm"
        style={{ border: '1px solid var(--border-technical)', background: 'var(--surface-container-low)', borderRadius: 8 }}
      >
        <svg
          className="h-5 w-5 shrink-0"
          style={{ color: 'var(--primary)' }}
          fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
        </svg>
        <p className="t-label-mono" style={{ color: 'var(--on-surface)' }}>
          Thanks — your feedback was recorded.
        </p>
      </motion.div>
    )
  }

  return (
    <Panel as="form" onSubmit={submit} icon="rate_review" title={title} description={hint}>
      {/* radiogroup rather than five loose buttons, so a screen reader
          announces this as one control with a current value. */}
      <div className="flex items-center gap-1" role="radiogroup" aria-label="Rating out of 5">
        {[1, 2, 3, 4, 5].map((value) => (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={rating === value}
            aria-label={`${value} out of 5`}
            onClick={() => setRating(value === rating ? 0 : value)}
            className="p-1 transition hover:scale-110"
            style={{ color: value <= rating ? 'var(--primary)' : 'var(--outline)' }}
          >
            <svg
              className="h-7 w-7"
              viewBox="0 0 24 24"
              fill={value <= rating ? 'currentColor' : 'none'}
              stroke="currentColor"
              strokeWidth="1.5"
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 3l2.9 5.9 6.5.9-4.7 4.6 1.1 6.5L12 17.8 6.2 20.9l1.1-6.5L2.6 9.8l6.5-.9L12 3z" />
            </svg>
          </button>
        ))}
        {rating > 0 && (
          <span className="t-label-mono ml-2 tabular-nums" style={{ color: 'var(--on-surface-variant)' }}>
            {rating}/5
          </span>
        )}
      </div>

      <textarea
        value={message}
        onChange={(event) => setMessage(event.target.value)}
        rows={3}
        placeholder="Anything we got wrong, or a project you expected to see?"
        aria-label="Feedback message"
        className="gm-input mt-4 w-full px-3 py-2 text-sm"
      />

      {error && <p className="t-body-md mt-2" style={{ color: '#ffb4ab', fontSize: 13 }}>{error}</p>}

      <div className="mt-4 flex items-center gap-3">
        <button
          type="submit"
          disabled={!canSubmit || status === 'sending'}
          className="btn-primary t-label-caps px-4 py-2"
        >
          {status === 'sending' ? 'Sending…' : 'Send feedback'}
        </button>
        {!canSubmit && (
          <span className="t-label-mono" style={{ color: 'var(--outline)', fontSize: 11 }}>
            Add a rating or a comment first.
          </span>
        )}
      </div>
    </Panel>
  )
}
