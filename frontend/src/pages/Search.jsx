import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { motion } from 'framer-motion'
import api from '../services/api'
import useAuth from '../hooks/useAuth.jsx'
import useFavorites from '../hooks/useFavorites'
import ProjectCard from '../components/ProjectCard'
import PageHeader from '../components/PageHeader'
import { SearchBar, FilterPanel } from '../components/SearchControls'
import { ErrorNotice, EmptyState } from '../components/Feedback'
import LandingHero from '../components/landing/LandingHero'
import AuthGateModal from '../components/AuthGateModal'
import { clearPendingQuery, setPendingQuery } from '../utils/pendingQuery'

/**
 * Tells the user when their own history moved the ranking, and lets them undo
 * it. Personalisation that a user cannot see or switch off is indistinguishable
 * from the ranking simply being wrong, so the control ships with the feature.
 */
function PersonalizationNotice({ info, enabled, onToggle }) {
  if (!enabled) {
    return (
      <button
        onClick={onToggle}
        className="t-label-mono transition hover:opacity-70"
        style={{ color: 'var(--outline)', fontSize: 12 }}
      >
        Personalisation off — turn on
      </button>
    )
  }

  // Enabled, but this device has nothing to learn from yet.
  if (!info?.applied) {
    return (
      <span className="t-label-mono" style={{ color: 'var(--outline)', fontSize: 12 }}>
        Save a project to personalise these results
      </span>
    )
  }

  const { favorites = 0, queries = 0 } = info.signals ?? {}
  const parts = [
    favorites > 0 && `${favorites} saved project${favorites === 1 ? '' : 's'}`,
    queries > 0 && `${queries} recent search${queries === 1 ? '' : 'es'}`,
  ].filter(Boolean)

  return (
    <span className="flex items-center gap-2">
      <span
        title={`Ranking blended with your profile at ${Math.round(info.weight * 100)}% weight`}
        className="gm-chip px-2.5 py-1"
        style={{ borderColor: 'var(--primary)', color: 'var(--primary)' }}
      >
        <span className="h-1.5 w-1.5 rounded-full" style={{ background: 'var(--primary)' }} />
        Personalised from {parts.join(' and ')}
      </span>
      <button
        onClick={onToggle}
        className="t-label-mono transition hover:opacity-70"
        style={{ color: 'var(--outline)', fontSize: 12 }}
      >
        Turn off
      </button>
    </span>
  )
}

// Demonstrate the hybrid engine (meaning + literal keywords), not just topic
// words — same intent as Dashboard's STARTERS chips, sized for this page.
const EXAMPLE_QUERIES = [
  'Find a beginner NLP project using Python',
  'AI healthcare project for 3 months',
  'Computer vision project using Flask',
  'Blockchain project for two students',
]

/** Search hero — the SearchBar itself is unchanged (shared, has mic support),
 * just wrapped in a card with example queries so it reads as an AI search
 * surface rather than a bare HTML form. */
function DiscoveryHero({ input, setInput, submit }) {
  return (
    <div className="glass-panel mb-8 p-5 sm:p-6" style={{ borderRadius: 8 }}>
      {/* `submit` takes an optional query so the mic button (and the example
          chips below) can pass a value straight through instead of relying
          on `input` state having caught up yet. */}
      <SearchBar value={input} onChange={setInput} onSubmit={submit} />
      <div className="mt-4 flex flex-wrap gap-2">
        {EXAMPLE_QUERIES.map((example) => (
          <button
            key={example}
            type="button"
            onClick={() => submit(example)}
            className="t-label-mono whitespace-nowrap px-3 py-1.5 transition hover:opacity-80"
            style={{ border: '1px solid var(--border-technical)', color: 'var(--on-surface-variant)', fontSize: 12, borderRadius: 999 }}
          >
            {example}
          </button>
        ))}
      </div>
    </div>
  )
}

/** Compact, always-visible explanation of why results are ranked the way
 * they are — reuses the same .flow-chain/.flow-step/.flow-callout system
 * the marketing page's "Hybrid Retrieval Engine" section already uses (see
 * components/landing/landing.css), just condensed to one row instead of a
 * full diagram. */
function SearchMethodExplainer() {
  return (
    <div className="mb-8">
      <span className="t-label-caps mb-3 block" style={{ color: 'var(--outline)', fontSize: 10 }}>
        Search method
      </span>
      <div className="flow-chain vertical">
        <div className="flow-chain nowrap" style={{ overflowX: 'auto' }}>
          <span className="flow-step">Semantic Search — Sentence Transformers</span>
          <span className="flow-arrow" aria-hidden="true">+</span>
          <span className="flow-step">Keyword Search — BM25</span>
        </div>
        <span className="flow-arrow" aria-hidden="true">↓</span>
        <div className="flow-callout">Hybrid Ranking — meaning + keywords</div>
      </div>
    </div>
  )
}

const SORTS = [
  { key: 'relevance', label: 'Relevance' },
  { key: 'difficulty', label: 'Difficulty' },
  { key: 'duration', label: 'Duration' },
]

/** Client-side reorder of the already-fetched result set — there is no
 * backend sort parameter, so "Relevance" is just the hybrid-ranked order
 * /api/search already returned. */
function SortControl({ value, onChange }) {
  return (
    <div className="inline-flex shrink-0" style={{ border: '1px solid var(--border-technical)', borderRadius: 8, padding: 2 }}>
      {SORTS.map((sort) => (
        <button
          key={sort.key}
          type="button"
          onClick={() => onChange(sort.key)}
          className="t-label-caps px-2.5 py-1.5 transition"
          style={
            value === sort.key
              ? { background: 'var(--surface-container-high)', color: 'var(--primary)', borderRadius: 6, fontSize: 10 }
              : { color: 'var(--on-surface-variant)', borderRadius: 6, fontSize: 10 }
          }
        >
          {sort.label}
        </button>
      ))}
    </div>
  )
}

function MobileFilterButton({ activeCount, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="t-label-caps inline-flex shrink-0 items-center gap-2 px-3 py-2 transition hover:bg-white/5 lg:hidden"
      style={{ border: '1px solid var(--border-technical)', color: 'var(--on-surface-variant)', borderRadius: 8, fontSize: 10.5 }}
    >
      <span className="material-symbols-outlined" style={{ fontSize: 16 }}>tune</span>
      Filters
      {activeCount > 0 && <span style={{ color: 'var(--primary)' }}>{activeCount}</span>}
    </button>
  )
}

/** FilterPanel in an off-canvas drawer below `lg` — same slide + backdrop
 * pattern as AppSidebar's mobile nav (see components/Layout.jsx), so
 * filters don't have to fight the result grid for width on a small screen. */
function MobileFilterDrawer({ open, onClose, filters, onChange }) {
  return (
    <>
      {open && (
        <div
          className="fixed inset-0 z-40 lg:hidden"
          style={{ background: 'rgba(0,0,0,0.6)' }}
          onClick={onClose}
          aria-hidden="true"
        />
      )}
      <div
        className={`fixed inset-y-0 right-0 z-50 h-full w-80 max-w-[85vw] overflow-y-auto p-4 transition-transform duration-200 lg:hidden ${open ? 'translate-x-0' : 'translate-x-full'}`}
        style={{ background: 'var(--surface-container-low)', borderLeft: '1px solid var(--border-technical)' }}
      >
        <div className="mb-3 flex items-center justify-between">
          <span className="t-label-caps" style={{ color: 'var(--outline)', fontSize: 10 }}>
            Filters
          </span>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close filters"
            className="grid h-8 w-8 place-items-center transition hover:bg-white/5"
            style={{ color: 'var(--outline)', borderRadius: 6 }}
          >
            <span className="material-symbols-outlined" style={{ fontSize: 18 }}>close</span>
          </button>
        </div>
        <FilterPanel filters={filters} onChange={onChange} />
      </div>
    </>
  )
}

/** Technical, in-brand replacement for a bare "Loading…" spinner — names
 * the three real retrieval stages the request is actually going through
 * (see backend/nlp/similarity.py) instead of a generic indicator. */
function SearchingState() {
  const steps = ['Semantic search', 'Keyword matching', 'Hybrid ranking']
  return (
    <div className="glass-panel p-6" style={{ borderRadius: 8 }}>
      <p className="t-label-caps mb-4" style={{ color: 'var(--outline)', fontSize: 10 }}>
        Searching project catalogue
      </p>
      <div className="space-y-3">
        {steps.map((step, i) => (
          <div key={step} className="flex items-center justify-between">
            <span className="t-label-mono" style={{ color: 'var(--on-surface-variant)', fontSize: 13 }}>
              {step}
            </span>
            <div className="flex items-center gap-1">
              {[0, 1, 2].map((dot) => (
                <motion.span
                  key={dot}
                  className="h-1 w-1 rounded-full"
                  style={{ background: 'var(--outline)' }}
                  animate={{ opacity: [0.3, 1, 0.3] }}
                  transition={{ duration: 1, repeat: Infinity, delay: i * 0.15 + dot * 0.15 }}
                />
              ))}
            </div>
          </div>
        ))}
      </div>
      <p className="t-body-md mt-4 pt-4" style={{ borderTop: '1px solid var(--border-technical)', color: 'var(--outline)', fontSize: 12.5 }}>
        Finding relevant projects…
      </p>
    </div>
  )
}

const NO_RESULTS_TIPS = ['Try a broader description', 'Remove a technology constraint', 'Search by project goal']

function NoResultsState() {
  return (
    <EmptyState title="No close matches found." hint="Hybrid search still couldn't find anything close enough to show.">
      <ul className="mx-auto max-w-xs space-y-1.5 text-left">
        {NO_RESULTS_TIPS.map((tip) => (
          <li key={tip} className="t-label-mono flex items-center gap-2" style={{ color: 'var(--on-surface-variant)', fontSize: 12.5 }}>
            <span style={{ color: 'var(--outline)' }} aria-hidden="true">→</span>
            {tip}
          </li>
        ))}
      </ul>
    </EmptyState>
  )
}

const DIFFICULTY_RANK = { Beginner: 0, Intermediate: 1, Advanced: 2 }

export default function Search() {
  // The query lives in the URL so a result set can be shared, bookmarked, and
  // survives a page refresh.
  const [searchParams, setSearchParams] = useSearchParams()
  const urlQuery = searchParams.get('q') ?? ''
  const navigate = useNavigate()
  const { user } = useAuth()

  const [input, setInput] = useState(urlQuery)
  const [filters, setFilters] = useState({})
  const [results, setResults] = useState(null)
  const [status, setStatus] = useState('idle')
  const [error, setError] = useState(null)
  const [authGateOpen, setAuthGateOpen] = useState(false)
  // On by default, matching the backend. Kept in component state rather than
  // the URL: it is a preference about how *you* see results, not part of the
  // result set that a shared link should reproduce.
  const [personalize, setPersonalize] = useState(true)
  // Display-only reorder of the same fetched set — see SortControl.
  const [sortBy, setSortBy] = useState('relevance')
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false)

  const { isFavorite, toggle } = useFavorites()

  const runSearch = useCallback(
    async (query, activeFilters, usePersonal) => {
      if (!query.trim()) return
      setStatus('loading')
      setError(null)
      try {
        const response = await api.search({
          query,
          ...activeFilters,
          top_k: 12,
          personalize: usePersonal,
        })
        setResults(response)
        setStatus('done')
      } catch (err) {
        setError(err.message)
        setStatus('error')
      }
    },
    [],
  )

  // Re-run whenever the URL query, the filters, or the personalisation
  // preference change. Filters deliberately do not need a second Search click —
  // changing one should update results.
  useEffect(() => {
    if (urlQuery) runSearch(urlQuery, filters, personalize)
  }, [urlQuery, filters, personalize, runSearch])

  const submit = (query = input) => {
    setInput(query)
    setSearchParams(query.trim() ? { q: query } : {})
  }

  // The landing hero's own box is the one place a signed-out visitor first
  // meets this app — search/chat now requires an account everywhere, so
  // this is where that gate lives. A signed-in visitor skips the modal
  // entirely; either way the query survives the redirect via
  // sessionStorage (Search.jsx unmounts on navigate, so component state
  // can't carry it) and Dashboard sends it the moment it mounts.
  const submitFromLanding = (query = input) => {
    const trimmed = (query ?? input).trim()
    if (!trimmed) return
    setInput(trimmed)
    setPendingQuery(trimmed)
    if (!user) {
      setAuthGateOpen(true)
      return
    }
    navigate('/dashboard')
  }

  const hasSearched = Boolean(urlQuery)

  const sortedData = useMemo(() => {
    if (!results?.data?.length) return []
    if (sortBy === 'difficulty') {
      return [...results.data].sort((a, b) => (DIFFICULTY_RANK[a.difficulty] ?? 0) - (DIFFICULTY_RANK[b.difficulty] ?? 0))
    }
    if (sortBy === 'duration') {
      return [...results.data].sort((a, b) => (a.duration_weeks ?? 0) - (b.duration_weeks ?? 0))
    }
    // 'relevance' — exactly the hybrid-ranked order the backend returned.
    return results.data
  }, [results, sortBy])

  const activeFilterCount = Object.values(filters).filter(Boolean).length

  return (
    <div>
      {/* Landing state gets the full "Gallery Mono" treatment (see DESIGN.md) —
          its own search input, gated behind sign-in (see submitFromLanding),
          then handed off to Dashboard. */}
      {!hasSearched && (
        <>
          <LandingHero value={input} onChange={setInput} onSubmit={submitFromLanding} />
          <AuthGateModal
            open={authGateOpen}
            onClose={() => {
              setAuthGateOpen(false)
              clearPendingQuery()
            }}
            onAuthenticated={() => {
              setAuthGateOpen(false)
              navigate('/dashboard')
            }}
            message="Sign in to search and chat with ProjectMind — your question will be right there when you land."
          />
        </>
      )}

      {hasSearched && (
        <div className="mx-auto max-w-6xl px-6 py-14">
          <PageHeader
            eyebrow="Project Discovery"
            title="Find the right project."
            description="Search the project catalogue using meaning, keywords, and hybrid ranking."
          />

          <DiscoveryHero input={input} setInput={setInput} submit={submit} />
          <SearchMethodExplainer />

          <div className="grid gap-6 lg:grid-cols-[260px_1fr]">
            <aside className="hidden lg:block lg:sticky lg:top-20 lg:self-start">
              <FilterPanel filters={filters} onChange={setFilters} />
            </aside>

            <section>
              {(status === 'loading' || status === 'idle') && <SearchingState />}
              {status === 'error' && <ErrorNotice message={error} onRetry={() => runSearch(urlQuery, filters, personalize)} />}

              {status === 'done' && results && (
                <>
                  <div className="mb-5 flex flex-wrap items-start justify-between gap-x-4 gap-y-3 pb-3" style={{ borderBottom: '1px solid var(--border-technical)' }}>
                    <div className="min-w-0">
                      <p className="t-label-mono" style={{ color: 'var(--primary)', fontSize: 15 }}>
                        {results.personalization?.applied ? 'Recommended for you' : 'Projects matching your search'}
                      </p>
                      <p className="t-body-md mt-1" style={{ color: 'var(--on-surface-variant)' }}>
                        <span className="t-label-mono tabular-nums" style={{ color: 'var(--on-surface)' }}>
                          {results.count}
                        </span>{' '}
                        project{results.count === 1 ? '' : 's'} for{' '}
                        <span style={{ color: 'var(--on-surface)' }}>“{results.query}”</span>
                      </p>
                    </div>

                    <div className="flex flex-wrap items-center gap-3">
                      <PersonalizationNotice
                        info={results.personalization}
                        enabled={personalize}
                        onToggle={() => setPersonalize((on) => !on)}
                      />
                      <MobileFilterButton activeCount={activeFilterCount} onClick={() => setMobileFiltersOpen(true)} />
                      {results.count > 0 && <SortControl value={sortBy} onChange={setSortBy} />}
                    </div>
                  </div>

                  {results.count === 0 ? (
                    <NoResultsState />
                  ) : (
                    <div className="grid gap-4 sm:grid-cols-2">
                      {sortedData.map((project, index) => (
                        <ProjectCard
                          key={project.project_id}
                          project={project}
                          index={index}
                          isFavorite={isFavorite(project.project_id)}
                          onToggleFavorite={toggle}
                        />
                      ))}
                    </div>
                  )}
                </>
              )}
            </section>
          </div>

          <MobileFilterDrawer
            open={mobileFiltersOpen}
            onClose={() => setMobileFiltersOpen(false)}
            filters={filters}
            onChange={setFilters}
          />
        </div>
      )}
    </div>
  )
}
