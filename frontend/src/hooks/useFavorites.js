import { useCallback, useEffect, useState } from 'react'
import api from '../services/api'

/**
 * Favourite state shared across the app.
 *
 * Kept as a Set of project ids so a card can answer "am I favourited?" in O(1)
 * without refetching. Toggling updates local state optimistically and rolls
 * back if the request fails — a star that silently does nothing is worse than
 * one that visibly reverts.
 */
export function useFavorites() {
  const [ids, setIds] = useState(() => new Set())
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    try {
      const { data } = await api.listFavorites()
      setIds(new Set(data.map((p) => p.project_id)))
    } catch {
      // A failed favourites fetch should not break the page the user is on.
      setIds(new Set())
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const toggle = useCallback(
    async (projectId) => {
      const wasFavorite = ids.has(projectId)

      setIds((prev) => {
        const next = new Set(prev)
        if (wasFavorite) next.delete(projectId)
        else next.add(projectId)
        return next
      })

      try {
        if (wasFavorite) await api.removeFavorite(projectId)
        else await api.addFavorite(projectId)
      } catch {
        setIds((prev) => {
          const next = new Set(prev)
          if (wasFavorite) next.add(projectId)
          else next.delete(projectId)
          return next
        })
      }
    },
    [ids],
  )

  return { favoriteIds: ids, isFavorite: (id) => ids.has(id), toggle, refresh, loading }
}

export default useFavorites
