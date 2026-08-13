import { Component } from 'react'
import '../components/landing/landing.css'

/**
 * Catches render-time exceptions anywhere below it in the tree.
 *
 * Without this, a thrown error in any page — a malformed API response
 * reaching `project.technologies.map(...)`, say — unmounts the whole React
 * tree and leaves a blank page with nothing but a console error. One
 * boundary around the routed content turns that into a recoverable,
 * on-brand state instead.
 */
export default class ErrorBoundary extends Component {
  state = { error: null }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    console.error('Unhandled render error:', error, info)
  }

  render() {
    if (this.state.error) {
      return (
        <div
          className="landing-mono mx-auto flex min-h-screen max-w-md flex-col items-center justify-center gap-3 px-4 text-center"
          style={{ background: 'var(--background)' }}
        >
          <div
            className="grid h-11 w-11 place-items-center rounded-full"
            style={{ border: '1px solid rgba(255,180,171,0.3)', color: '#ffb4ab' }}
          >
            <svg className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <circle cx="12" cy="12" r="9" />
              <path strokeLinecap="round" d="M12 8v5M12 16.5v.01" />
            </svg>
          </div>
          <p className="t-label-mono" style={{ color: 'var(--on-surface)' }}>Something broke.</p>
          <p className="t-body-md" style={{ color: 'var(--on-surface-variant)' }}>
            Reload the page — if it keeps happening, tell us what you were doing.
          </p>
          <button
            onClick={() => window.location.reload()}
            className="btn-primary t-label-caps mt-2 px-4 py-2"
          >
            Reload
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
