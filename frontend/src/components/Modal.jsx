import { useEffect } from 'react'
import { createPortal } from 'react-dom'
import { AnimatePresence, motion } from 'framer-motion'
import './landing/landing.css'

/**
 * Generic dialog scaffold — portal + blurred backdrop + glass-panel box +
 * close button, the same anatomy AuthGateModal already uses, pulled out so
 * other dialogs (pages/Ideate.jsx's refine/uniqueness/roadmap panels) don't
 * each re-hand-roll it.
 */
export default function Modal({ open, onClose, title, eyebrow, children, maxWidth = 560 }) {
  useEffect(() => {
    if (!open) return
    const onKeyDown = (event) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open, onClose])

  if (!open) return null

  return createPortal(
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.15 }}
        className="landing-mono fixed inset-0 z-[100] flex items-center justify-center p-6"
        style={{ background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(10px)', WebkitBackdropFilter: 'blur(10px)' }}
        onClick={onClose}
      >
        <motion.div
          initial={{ opacity: 0, y: 12, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 12, scale: 0.98 }}
          transition={{ duration: 0.2 }}
          onClick={(event) => event.stopPropagation()}
          className="glass-panel relative w-full max-h-[85vh] overflow-y-auto p-7"
          style={{ borderRadius: 12, maxWidth }}
        >
          <button
            onClick={onClose}
            aria-label="Close"
            className="absolute right-4 top-4 grid h-8 w-8 shrink-0 place-items-center transition hover:bg-white/5"
            style={{ color: 'var(--outline)', borderRadius: 6 }}
          >
            <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path strokeLinecap="round" d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>

          {eyebrow && (
            <span
              className="t-label-caps mb-4 inline-block px-3 py-1"
              style={{ border: '1px solid var(--border-technical)', background: 'var(--surface-glass)', color: 'var(--on-surface-variant)', borderRadius: 999 }}
            >
              {eyebrow}
            </span>
          )}
          {title && (
            <h2 className="t-label-mono mb-5 pr-8" style={{ color: 'var(--primary)', fontSize: 17 }}>
              {title}
            </h2>
          )}
          {children}
        </motion.div>
      </motion.div>
    </AnimatePresence>,
    document.body,
  )
}
