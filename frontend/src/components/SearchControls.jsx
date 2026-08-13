import { useEffect, useState } from 'react'
import api from '../services/api'
import useVoiceSearch from '../hooks/useVoiceSearch'
import Panel from './Panel'

/**
 * Microphone button — fills the search box by speaking instead of typing.
 *
 * Submits immediately on a result rather than waiting for the user to also
 * press "Search": the result callback passes the transcript straight to
 * `onSubmit`, sidestepping the stale-closure problem of updating `value` via
 * `onChange` and then reading it back before React has re-rendered.
 */
function MicButton({ onTranscript }) {
  const { supported, listening, error, start, stop } = useVoiceSearch()

  if (!supported) return null

  return (
    <button
      type="button"
      onClick={() => (listening ? stop() : start(onTranscript))}
      aria-label={listening ? 'Stop voice search' : 'Search by voice'}
      aria-pressed={listening}
      title={error ?? (listening ? 'Listening… click to stop' : 'Search by voice')}
      className="absolute right-3 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center transition hover:bg-white/5"
      style={{ color: listening ? 'var(--primary)' : 'var(--outline)', borderRadius: 6 }}
    >
      {listening && (
        <span
          className="absolute inset-0 animate-ping"
          style={{ background: 'rgba(255,255,255,0.15)', borderRadius: 6 }}
          aria-hidden="true"
        />
      )}
      <svg className="relative h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
        <rect x="9" y="3" width="6" height="11" rx="3" />
        <path strokeLinecap="round" d="M5 11a7 7 0 0014 0M12 18v3" />
      </svg>
    </button>
  )
}

export function SearchBar({ value, onChange, onSubmit, autoFocus = false }) {
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        onSubmit()
      }}
      className="flex flex-col gap-2 sm:flex-row"
    >
      <div className="relative flex-1">
        <svg
          className="pointer-events-none absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2"
          style={{ color: 'var(--outline)' }}
          fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"
        >
          <circle cx="11" cy="11" r="7" />
          <path strokeLinecap="round" d="M21 21l-4.3-4.3" />
        </svg>
        <input
          value={value}
          autoFocus={autoFocus}
          onChange={(event) => onChange(event.target.value)}
          placeholder="Describe the project you want, in plain English…"
          aria-label="Search projects"
          className="gm-input w-full py-3.5 pl-12 pr-12"
        />
        <MicButton onTranscript={onSubmit} />
      </div>
      <button type="submit" className="btn-primary t-label-caps px-7 py-3.5">
        Search
      </button>
    </form>
  )
}

/** Native select restyled: the default control is the most obviously unstyled
 *  element on the page, so it gets a matching border, padding and our own
 *  chevron. `appearance-none` removes the platform arrow that would otherwise
 *  sit alongside ours. */
function Select({ label, value, onChange, children }) {
  return (
    <label className="block">
      <span className="t-label-caps mb-1.5 block" style={{ color: 'var(--outline)', fontSize: 10 }}>
        {label}
      </span>
      <div className="relative">
        <select
          value={value}
          onChange={onChange}
          className="gm-input w-full appearance-none px-3 py-2 pr-9 text-sm"
        >
          {children}
        </select>
        <svg
          className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2"
          style={{ color: 'var(--outline)' }}
          fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M6 9l6 6 6-6" />
        </svg>
      </div>
    </label>
  )
}

/**
 * Technology filter — multiple values.
 *
 * The backend has always matched a list of technologies with ANY semantics
 * (see HybridRetriever._mask); this control is what finally lets a user send
 * more than one.
 *
 * Chips-plus-picker rather than a native multi-select: there are ~88
 * technologies in the corpus, and a multi-select long enough to hold them is
 * both unreadable and painful on touch. The picker also hides values already
 * chosen, so the same technology cannot be added twice.
 */
function TechnologyFilter({ selected, options, onChange }) {
  const available = options.filter((t) => !selected.includes(t))

  // An empty array must become undefined, not [], or the "active filters"
  // count treats it as a live filter — [] is truthy in JS.
  const commit = (next) => onChange(next.length ? next : undefined)

  return (
    <div>
      <span className="t-label-caps mb-1.5 block" style={{ color: 'var(--outline)', fontSize: 10 }}>
        Technology
      </span>

      {selected.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-1.5">
          {selected.map((tech) => (
            <span
              key={tech}
              className="gm-chip py-0.5 pl-2 pr-1"
              style={{ borderColor: 'var(--primary)', color: 'var(--primary)' }}
            >
              {tech}
              <button
                type="button"
                onClick={() => commit(selected.filter((t) => t !== tech))}
                aria-label={`Remove ${tech} filter`}
                className="p-0.5 transition hover:opacity-70"
              >
                <svg className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24">
                  <path strokeLinecap="round" d="M6 6l12 12M18 6L6 18" />
                </svg>
              </button>
            </span>
          ))}
        </div>
      )}

      <div className="relative">
        <select
          // Always reset to the placeholder: this select is an "add" action,
          // not a field holding a current value — the chips above are the value.
          value=""
          onChange={(event) => {
            if (event.target.value) commit([...selected, event.target.value])
          }}
          aria-label="Add a technology filter"
          className="gm-input w-full appearance-none px-3 py-2 pr-9 text-sm"
        >
          <option value="">
            {selected.length ? 'Add another technology…' : 'Any technology'}
          </option>
          {available.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <svg
          className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2"
          style={{ color: 'var(--outline)' }}
          fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M6 9l6 6 6-6" />
        </svg>
      </div>

      {selected.length > 1 && (
        <p className="t-label-mono mt-1.5" style={{ color: 'var(--outline)', fontSize: 11 }}>
          Showing projects using any of these.
        </p>
      )}
    </div>
  )
}

/**
 * Filter panel.
 *
 * Options come from /api/filters rather than being hardcoded: the technology
 * list is derived from what is actually in the database, so we never offer a
 * filter that would return nothing.
 */
export function FilterPanel({ filters, onChange }) {
  const [options, setOptions] = useState({ domains: [], difficulties: [], technologies: [] })

  useEffect(() => {
    api
      .filters()
      .then(({ data }) => setOptions(data))
      .catch(() => {
        /* Filters are an enhancement; search still works without them. */
      })
  }, [])

  const set = (key, value) => onChange({ ...filters, [key]: value || undefined })

  const activeCount = Object.values(filters).filter(Boolean).length

  return (
    <Panel
      icon="tune"
      title="Filters"
      description={activeCount > 0 ? `${activeCount} active` : 'Narrow the catalogue'}
      compact
      actions={
        activeCount > 0 && (
          <button
            onClick={() => onChange({})}
            className="t-label-mono transition hover:opacity-70"
            style={{ color: 'var(--on-surface-variant)', fontSize: 11 }}
          >
            Clear all
          </button>
        )
      }
    >
      <div className="space-y-4">
        <Select label="Domain" value={filters.domain ?? ''} onChange={(e) => set('domain', e.target.value)}>
          <option value="">Any domain</option>
          {options.domains.map((d) => <option key={d} value={d}>{d}</option>)}
        </Select>

        <Select label="Difficulty" value={filters.difficulty ?? ''} onChange={(e) => set('difficulty', e.target.value)}>
          <option value="">Any difficulty</option>
          {options.difficulties.map((d) => <option key={d} value={d}>{d}</option>)}
        </Select>

        <TechnologyFilter
          selected={filters.technologies ?? []}
          options={options.technologies}
          onChange={(next) => onChange({ ...filters, technologies: next })}
        />

        <label className="block">
          <span className="t-label-caps mb-1.5 flex items-baseline justify-between" style={{ color: 'var(--outline)', fontSize: 10 }}>
            <span>Max duration</span>
            <span className="t-label-mono tabular-nums" style={{ color: 'var(--on-surface)' }}>
              {filters.max_duration_weeks ? `${filters.max_duration_weeks} weeks` : 'Any'}
            </span>
          </span>
          <input
            type="range" min="2" max="16" step="1"
            value={filters.max_duration_weeks ?? 16}
            onChange={(e) => {
              const weeks = Number(e.target.value)
              // 16 is the top of the range, which means "no limit" rather than
              // an actual 16-week ceiling.
              set('max_duration_weeks', weeks === 16 ? undefined : weeks)
            }}
            className="w-full accent-white"
          />
        </label>
      </div>
    </Panel>
  )
}
