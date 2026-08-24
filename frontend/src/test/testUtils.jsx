import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { AuthProvider } from '../hooks/useAuth.jsx'

/**
 * Renders `ui` inside the same providers every real route gets — a Router
 * (so useNavigate/useSearchParams/Link work) and the real AuthProvider
 * (so useAuth() reflects real signed-in/signed-out logic instead of a
 * second, parallel mock of it). Call sites still mock services/api.js
 * itself (via `vi.mock('../../services/api')` at the top of the test file)
 * — that's the actual network boundary; the auth *logic* on top of it is
 * exactly what's under test in several of these suites, so it stays real.
 *
 * Pass `authToken` to start already signed in — AuthProvider's own mount
 * effect calls api.me() whenever a token is present, so the caller's api
 * mock must resolve `me` accordingly (see each test file's own setup).
 */
export function renderWithProviders(ui, { route = '/', authToken } = {}) {
  if (authToken) {
    window.localStorage.setItem('projectmind.authToken', authToken)
  }
  return render(<MemoryRouter initialEntries={[route]}>{withAuth(ui)}</MemoryRouter>)
}

function withAuth(ui) {
  return <AuthProvider>{ui}</AuthProvider>
}
