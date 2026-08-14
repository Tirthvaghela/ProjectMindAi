import { lazy, Suspense } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import Search from './pages/Search'
import { EmptyState, Spinner } from './components/Feedback'

// Search stays a static import — it's the index route (query-results deep
// links like History's "run again" still land here). Everything else is
// fetched only when actually navigated to.
const ResumeMatch = lazy(() => import('./pages/ResumeMatch'))
const UniquenessCheck = lazy(() => import('./pages/UniquenessCheck'))
const Ideate = lazy(() => import('./pages/Ideate'))
const Account = lazy(() => import('./pages/Account'))
const Dashboard = lazy(() => import('./pages/Dashboard'))
const Teams = lazy(() => import('./pages/Teams'))
const TeamRoom = lazy(() => import('./pages/TeamRoom'))
const ProjectDetail = lazy(() => import('./pages/ProjectDetail'))
const IdeaDetail = lazy(() => import('./pages/IdeaDetail'))
const Favorites = lazy(() => import('./pages/Favorites'))
const History = lazy(() => import('./pages/History'))

export default function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<Spinner />}>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Search />} />
            <Route path="resume-match" element={<ResumeMatch />} />
            <Route path="uniqueness" element={<UniquenessCheck />} />
            <Route path="ideate" element={<Ideate />} />
            <Route path="account" element={<Account />} />
            <Route path="dashboard" element={<Dashboard />} />
            <Route path="teams" element={<Teams />} />
            <Route path="teams/:id" element={<TeamRoom />} />
            <Route path="project/:id" element={<ProjectDetail />} />
            <Route path="idea" element={<IdeaDetail />} />
            <Route path="favorites" element={<Favorites />} />
            <Route path="history" element={<History />} />
            <Route
              path="*"
              element={<EmptyState title="Page not found" hint="That route does not exist." />}
            />
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  )
}
