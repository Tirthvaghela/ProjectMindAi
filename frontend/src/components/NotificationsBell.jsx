import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import api from '../services/api'
import { formatRelative } from '../utils/time'

/**
 * Polls rather than pushes — consistent with the team message board, and for
 * the same reason: infrequent events, no websocket infra this app otherwise
 * needs. 30s is frequent enough that "someone joined your team" feels timely
 * without hammering the API from every open tab.
 */
export default function NotificationsBell() {
  const [open, setOpen] = useState(false)
  const [items, setItems] = useState([])
  const [unread, setUnread] = useState(0)
  const ref = useRef(null)

  const load = () => {
    api
      .notifications(15)
      .then((res) => {
        setItems(res.data)
        setUnread(res.unread)
      })
      .catch(() => {
        /* Notifications are an enhancement; a failed poll should not disturb the page. */
      })
  }

  useEffect(() => {
    load()
    const interval = setInterval(load, 30000)
    return () => clearInterval(interval)
  }, [])

  useEffect(() => {
    const onClickOutside = (event) => {
      if (ref.current && !ref.current.contains(event.target)) setOpen(false)
    }
    document.addEventListener('mousedown', onClickOutside)
    return () => document.removeEventListener('mousedown', onClickOutside)
  }, [])

  const openPanel = () => {
    setOpen((o) => !o)
  }

  // Marks just this one read, on click — separate from openPanel's old
  // "mark everything read the moment you open the panel" behaviour, which
  // never gave a reader the chance to actually see what was unread before
  // it was cleared. Local-first (flips the item + decrements the badge
  // immediately) since waiting on the network here would make every click
  // feel laggy for something this low-stakes; a failed request just leaves
  // it unread until the next poll, no rollback needed.
  const markRead = (notification) => {
    if (notification.read) return
    setItems((current) => current.map((n) => (n.notification_id === notification.notification_id ? { ...n, read: true } : n)))
    setUnread((n) => Math.max(0, n - 1))
    api.markNotificationRead(notification.notification_id).catch(() => {
      /* Next successful poll will reconcile the read state either way. */
    })
  }

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={openPanel}
        aria-label={unread > 0 ? `Notifications, ${unread} unread` : 'Notifications'}
        className="relative grid h-9 w-9 shrink-0 place-items-center transition hover:bg-white/5"
        style={{ border: '1px solid var(--border-technical)', color: 'var(--on-surface-variant)', borderRadius: 8 }}
      >
        <svg className="h-[18px] w-[18px]" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M15 17h5l-1.4-1.4A2 2 0 0118 14.2V11a6 6 0 10-12 0v3.2a2 2 0 01-.6 1.4L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
        </svg>
        {unread > 0 && (
          <span
            className="t-label-mono absolute -right-0.5 -top-0.5 grid h-4 min-w-4 place-items-center rounded-full px-1"
            style={{ background: 'var(--primary)', color: 'var(--on-primary)', fontSize: 10, fontWeight: 600 }}
          >
            {unread > 9 ? '9+' : unread}
          </span>
        )}
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.15 }}
            className="glass-panel absolute right-0 z-50 mt-2 w-80 overflow-hidden"
            style={{ background: 'var(--surface-container)', borderRadius: 8 }}
          >
            <div
              className="flex items-center justify-between px-4 py-2.5"
              style={{ borderBottom: '1px solid var(--border-technical)' }}
            >
              <span className="t-label-caps" style={{ color: 'var(--outline)' }}>Notifications</span>
              {unread > 0 && (
                <button
                  type="button"
                  onClick={() => {
                    setItems((current) => current.map((n) => ({ ...n, read: true })))
                    setUnread(0)
                    api.markAllNotificationsRead().catch(() => {})
                  }}
                  className="t-label-caps transition hover:opacity-75"
                  style={{ color: 'var(--primary)', fontSize: 10.5 }}
                >
                  Mark all read
                </button>
              )}
            </div>
            {items.length === 0 ? (
              <p className="t-body-md px-4 py-6 text-center" style={{ color: 'var(--outline)', fontSize: 13 }}>Nothing yet</p>
            ) : (
              <ul className="max-h-80 overflow-y-auto">
                {items.map((n) => (
                  <li key={n.notification_id} style={{ borderTop: '1px solid var(--border-technical)' }} className="first:border-t-0">
                    <Link
                      to={n.team_id ? `/teams/${n.team_id}` : '/teams'}
                      onClick={() => {
                        markRead(n)
                        setOpen(false)
                      }}
                      className="flex items-start gap-2 px-4 py-3 transition hover:bg-white/5"
                      style={{ background: n.read ? 'transparent' : 'var(--surface-glass)' }}
                    >
                      <span
                        aria-hidden="true"
                        className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full"
                        style={{ background: n.read ? 'transparent' : 'var(--primary)' }}
                      />
                      <div className="min-w-0">
                        <p className="t-label-mono" style={{ color: 'var(--on-surface)' }}>{n.title}</p>
                        <p className="t-body-md mt-0.5" style={{ color: 'var(--on-surface-variant)', fontSize: 12.5 }}>{n.body}</p>
                        <p className="t-label-mono mt-1" style={{ color: 'var(--outline)', fontSize: 11 }}>{formatRelative(n.created_at)}</p>
                      </div>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
