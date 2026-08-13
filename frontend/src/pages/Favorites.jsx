import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import api from '../services/api'
import useFavorites from '../hooks/useFavorites'
import ProjectCard from '../components/ProjectCard'
import PageHeader from '../components/PageHeader'
import { Spinner, ErrorNotice, EmptyState } from '../components/Feedback'

export default function Favorites() {
  const [projects, setProjects] = useState([])
  const [status, setStatus] = useState('loading')
  const [error, setError] = useState(null)
  const { isFavorite, toggle } = useFavorites()

  const load = () => {
    setStatus('loading')
    api
      .listFavorites()
      .then((res) => {
        setProjects(res.data)
        setStatus('done')
      })
      .catch((err) => {
        setError(err.message)
        setStatus('error')
      })
  }

  useEffect(load, [])

  const handleToggle = async (id) => {
    await toggle(id)
    // Removing from this page should make the card disappear immediately
    // rather than leaving a stale un-starred card behind.
    setProjects((current) => current.filter((p) => p.project_id !== id))
  }

  if (status === 'loading') return <div className="mx-auto max-w-6xl px-6 py-14"><Spinner label="Loading favourites…" /></div>
  if (status === 'error') return <div className="mx-auto max-w-6xl px-6 py-14"><ErrorNotice message={error} onRetry={load} /></div>

  return (
    <div className="mx-auto max-w-6xl px-6 py-14">
      <PageHeader
        title="Saved projects"
        description={
          projects.length > 0
            ? `${projects.length} project${projects.length === 1 ? '' : 's'} you starred, kept in this browser.`
            : 'Projects you star are kept here, in this browser.'
        }
      />

      {projects.length === 0 ? (
        <EmptyState title="No saved projects yet" hint="Tap the star on any project to save it here.">
          <Link to="/dashboard" className="btn-primary t-label-caps inline-block px-4 py-2">
            Start searching
          </Link>
        </EmptyState>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {projects.map((project, index) => (
            <ProjectCard
              key={project.project_id}
              project={project}
              index={index}
              isFavorite={isFavorite(project.project_id)}
              onToggleFavorite={handleToggle}
            />
          ))}
        </div>
      )}
    </div>
  )
}
