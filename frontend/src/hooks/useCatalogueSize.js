import { useEffect, useState } from 'react'
import api from '../services/api'

/**
 * The live number of projects in the catalogue, from GET /api/projects (its
 * `total`, a plain count query) — so a page that says "N projects indexed"
 * can never go stale when the catalogue grows. One request per page load,
 * shared by every component that asks; `null` until it is known, and `null`
 * for good if the request fails, in which case callers should show wording
 * with no number rather than a guess.
 */
let known = null
let inflight = null

export function resetCatalogueSize() {
  known = null
  inflight = null
}

function load() {
  if (!inflight) {
    // Promise.resolve().then(...) so a synchronous throw, or a missing
    // response, degrades to "unknown" instead of breaking the page.
    inflight = Promise.resolve()
      .then(() => api.listProjects({ limit: 1 }))
      .then((response) => {
        if (Number.isInteger(response?.total)) known = response.total
        return known
      })
      .catch(() => null)
      .finally(() => {
        inflight = null
      })
  }
  return inflight
}

export default function useCatalogueSize() {
  const [size, setSize] = useState(known)

  useEffect(() => {
    if (known !== null) return undefined
    let active = true
    load().then((value) => {
      if (active && value !== null) setSize(value)
    })
    return () => {
      active = false
    }
  }, [])

  return size
}
