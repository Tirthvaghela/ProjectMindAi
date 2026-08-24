import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// React Testing Library doesn't auto-clean between tests under Vitest the
// way it does under Jest — without this, a component left mounted by one
// test leaks into the next test's DOM queries.
afterEach(() => {
  cleanup()
})

// jsdom implements no real layout/scrolling, so it has no scrollIntoView at
// all (Dashboard.jsx and others call it to keep the latest message in view)
// — a no-op stub is enough since tests only assert on rendered content, not
// actual scroll position.
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {}
}

// jsdom has no real layout engine, so framer-motion's animation internals
// (which probe for it) log noisy warnings that have nothing to do with any
// test's own behaviour — silenced here rather than per test file.
const originalWarn = console.warn
console.warn = (...args) => {
  if (typeof args[0] === 'string' && args[0].includes('Support for defaultProps')) return
  originalWarn(...args)
}
