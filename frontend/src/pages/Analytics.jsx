import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import api from '../services/api'
import PageHeader from '../components/PageHeader'
import { Spinner, ErrorNotice } from '../components/Feedback'

/**
 * Hero number.
 *
 * The value is set in primary ink, not an accent colour. A coloured number
 * reads as a series identity — as though it keyed to something in a chart —
 * when it is really just a total. The label above it carries the meaning.
 */
function Stat({ label, value }) {
  return (
    <div className="glass-panel p-5" style={{ borderRadius: 8 }}>
      <p className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>{label}</p>
      <p className="t-headline-lg mt-1.5 tabular-nums" style={{ color: 'var(--primary)', fontSize: 32 }}>
        {value}
      </p>
    </div>
  )
}

/**
 * Horizontal bar chart.
 *
 * Bars are scaled against the largest value rather than the total, so the
 * biggest category always fills the row and small differences stay readable.
 * Monochrome, per DESIGN.md's "strictly monochrome charts" rule — a single
 * white fill against a dim track, not a colour-per-series.
 */
function BarChart({ title, rows, labelKey = 'name' }) {
  if (!rows?.length) return null
  const max = Math.max(...rows.map((r) => r.count), 1)

  return (
    <div className="glass-panel p-5" style={{ borderRadius: 8 }}>
      <h2 className="t-label-mono mb-4" style={{ color: 'var(--primary)', fontSize: 14 }}>{title}</h2>
      <div className="space-y-2">
        {rows.map((row, index) => (
          <div
            key={row[labelKey]}
            // One series, so the value is readable directly off each row; the
            // native tooltip carries the full label when it is truncated.
            title={`${row[labelKey]}: ${row.count}`}
            className="flex items-center gap-3"
          >
            <span className="t-body-md w-40 shrink-0 truncate" style={{ color: 'var(--on-surface-variant)', fontSize: 13 }}>
              {row[labelKey]}
            </span>
            {/* Track stays recessive; only the data-end is rounded, so the bar
                reads as anchored to the baseline rather than floating. */}
            <div className="h-4 flex-1 overflow-hidden rounded-sm" style={{ background: 'var(--surface-container-high)' }}>
              <motion.div
                className="h-full rounded-r-sm"
                style={{ background: 'var(--primary)' }}
                initial={{ width: 0 }}
                animate={{ width: `${(row.count / max) * 100}%` }}
                transition={{ duration: 0.5, delay: index * 0.04 }}
              />
            </div>
            <span className="t-label-mono w-8 shrink-0 text-right tabular-nums" style={{ color: 'var(--on-surface)' }}>
              {row.count}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function Analytics() {
  const [stats, setStats] = useState(null)
  const [status, setStatus] = useState('loading')
  const [error, setError] = useState(null)

  const load = () => {
    setStatus('loading')
    api
      .analytics()
      .then((res) => {
        setStats(res.data)
        setStatus('done')
      })
      .catch((err) => {
        setError(err.message)
        setStatus('error')
      })
  }

  useEffect(load, [])

  if (status === 'loading') return <div className="mx-auto max-w-6xl px-6 py-14"><Spinner label="Crunching numbers…" /></div>
  if (status === 'error') return <div className="mx-auto max-w-6xl px-6 py-14"><ErrorNotice message={error} onRetry={load} /></div>

  return (
    <div className="mx-auto max-w-6xl px-6 py-14">
      <PageHeader
        title="Analytics"
        description="What is in the catalogue, and what people have been searching for."
      />

      <div className="mb-4 grid gap-4 sm:grid-cols-2">
        <Stat label="Projects in catalogue" value={stats.total_projects} />
        <Stat label="Searches performed" value={stats.total_searches} />
      </div>

      {/* items-start: these two charts have very different row counts, and
          stretching the short one to match the tall one leaves a large empty
          panel. Let each size to its own content. */}
      <div className="grid items-start gap-4 lg:grid-cols-2">
        <BarChart title="Projects by domain" rows={stats.by_domain} />
        <BarChart title="Projects by difficulty" rows={stats.by_difficulty} />
      </div>

      <div className="mt-4 grid gap-4">
        <BarChart title="Most used technologies" rows={stats.top_technologies} />

        {stats.trending_searches?.length > 0 && (
          <BarChart title="Trending searches" rows={stats.trending_searches} labelKey="query" />
        )}
      </div>
    </div>
  )
}
