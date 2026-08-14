import { useEffect } from 'react'

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'

/**
 * Keyboard-accessible dialog behavior shared by Modal.jsx and
 * AuthGateModal.jsx: Escape closes, Tab/Shift+Tab cycle within `dialogRef`
 * only (without this, a keyboard user can Tab straight out into the dimmed
 * background page while the dialog is still visually blocking it), focus
 * moves into the dialog on open, and returns to whatever had focus before it
 * opened once it closes.
 */
export function useFocusTrap(dialogRef, open, onClose) {
  useEffect(() => {
    if (!open) return
    const previouslyFocused = document.activeElement

    const frame = requestAnimationFrame(() => {
      // Respect an element that already claimed focus via its own autoFocus
      // (e.g. AuthGateModal's email field) rather than stealing it back.
      if (dialogRef.current?.contains(document.activeElement)) return
      const focusable = dialogRef.current?.querySelectorAll(FOCUSABLE_SELECTOR)
      ;(focusable?.[0] ?? dialogRef.current)?.focus()
    })

    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        onClose()
        return
      }
      if (event.key !== 'Tab' || !dialogRef.current) return
      const focusable = Array.from(dialogRef.current.querySelectorAll(FOCUSABLE_SELECTOR))
      if (focusable.length === 0) {
        event.preventDefault()
        return
      }
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => {
      cancelAnimationFrame(frame)
      document.removeEventListener('keydown', onKeyDown)
      previouslyFocused?.focus?.()
    }
  }, [open, onClose, dialogRef])
}
