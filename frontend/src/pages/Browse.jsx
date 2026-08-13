import { useEffect, useState } from 'react'
import api from '../services/api'
import useFavorites from '../hooks/useFavorites'
import ProjectCard from '../components/ProjectCard'
import PageHeader from '../components/PageHeader'
import { FilterPanel } from '../components/SearchControls'
import { Spinner, ErrorNotice, EmptyState } from '../components/Feedback'

const PAGE_SIZE = 12

export default function Browse() {
  const [filters, setFilters] = useState({})
  const [page, setPage] = useState(0)
  const [response, setResponse] = useState(null)
  const [status, setStatus] = useState('loading')
  const [error, setError] = useState(null)
  const { isFavorite, toggle } = useFavorites()

  // Changing a filter must reset to page 0, or you can land on page 3 of a
  // result set that now only has one page and see an empty grid.
  useEffect(() => setPage(0), [filters])

  useEffect(() => {
    setStatus('loading')
    const params = { limit: PAGE_SIZE, skip: page * PAGE_SIZE, ...filters }
    if (params.technologies) params.technologies = params.technologies.join(',')

    api
      .listProjects(params)
      .then((res) => {
        setResponse(res)
        setStatus('done')
      })
      .catch((err) => {
        setError(err.message)
        setStatus('error')
      })
  }, [filters, page])

  return (
    <div className="mx-auto max-w-6xl px-6 py-14">
      <PageHeader
        title="Browse all projects"
        description="The full catalogue, newest first. Narrow it with the filters."
      />

      <div className="grid gap-6 lg:grid-cols-[260px_1fr]">
        <aside className="lg:sticky lg:top-20 lg:self-start">
          <FilterPanel filters={filters} onChange={setFilters} />
        </aside>

        <section>
          {status === 'loading' && <Spinner />}
          {status === 'error' && <ErrorNotice message={error} />}

          {status === 'done' && response && (
            <>
              <p className="t-body-md mb-5 pb-3" style={{ borderBottom: '1px solid var(--border-technical)', color: 'var(--on-surface-variant)' }}>
                <span className="t-label-mono tabular-nums" style={{ color: 'var(--on-surface)' }}>
                  {response.total}
                </span>{' '}
                project{response.total === 1 ? '' : 's'}
                {response.total > 0 &&
                  ` · showing ${response.skip + 1}–${Math.min(response.skip + PAGE_SIZE, response.total)}`}
              </p>

              {response.total === 0 ? (
                <EmptyState title="Nothing matches those filters" hint="Try clearing one of them." />
              ) : (
                <>
                  <div className="grid gap-4 sm:grid-cols-2">
                    {response.data.map((project, index) => (
                      <ProjectCard
                        key={project.project_id}
                        project={project}
                        index={index}
                        isFavorite={isFavorite(project.project_id)}
                        onToggleFavorite={toggle}
                      />
                    ))}
                  </div>

                  <div className="mt-8 flex items-center justify-center gap-3">
                    <button
                      onClick={() => setPage((p) => Math.max(0, p - 1))}
                      disabled={page === 0}
                      className="btn-secondary t-label-caps px-4 py-2"
                    >
                      Previous
                    </button>
                    <span className="t-label-mono tabular-nums" style={{ color: 'var(--on-surface-variant)' }}>
                      Page {page + 1}
                    </span>
                    <button
                      onClick={() => setPage((p) => p + 1)}
                      disabled={!response.has_more}
                      className="btn-secondary t-label-caps px-4 py-2"
                    >
                      Next
                    </button>
                  </div>
                </>
              )}
            </>
          )}
        </section>
      </div>
    </div>
  )
}
