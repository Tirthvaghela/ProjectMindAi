import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { AuthProvider } from '../hooks/useAuth.jsx'
import Layout from './Layout'
import api from '../services/api'

vi.mock('../services/api', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    default: Object.fromEntries(Object.keys(actual.default).map((key) => [key, vi.fn()])),
  }
})

function renderTeamsRoute() {
  return render(
    <MemoryRouter initialEntries={['/teams']}>
      <AuthProvider>
        <Routes>
          <Route element={<Layout />}>
            <Route path="teams" element={<div>Teams page content</div>} />
          </Route>
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  window.localStorage.clear()
  vi.mocked(api.me).mockReset()
  vi.mocked(api.health).mockResolvedValue({ status: 'ok' })
})

describe('Layout — account-gated route, signed out', () => {
  it('renders the bare entry chrome instead of the full app shell', async () => {
    renderTeamsRoute()

    // The route's own content still renders — Layout only changes the
    // chrome around it, never what's fetched or shown (see Teams.jsx's own
    // sign-in gate for the actual "you can't see teams" behaviour).
    expect(await screen.findByText('Teams page content')).toBeInTheDocument()

    // Full-shell-only chrome must be entirely absent: the sidebar's "New
    // chat" action and workspace nav links (AppSidebar.jsx) don't belong on
    // what is effectively an entry screen for a signed-out visitor. ("Teams"
    // itself appears twice normally — as a nav link and a page heading — so
    // "Résumé Match", a nav-only link, is the unambiguous marker here.)
    expect(screen.queryByText('New chat')).not.toBeInTheDocument()
    expect(screen.queryByText('Résumé Match')).not.toBeInTheDocument()
  })
})

describe('Layout — account-gated route, signed in', () => {
  it('renders the full app shell as normal', async () => {
    window.localStorage.setItem('projectmind.authToken', 'tok-1')
    vi.mocked(api.me).mockResolvedValue({ data: { user_id: 'u1', name: 'Alex', email: 'alex@example.com' } })
    vi.mocked(api.listConversations).mockResolvedValue({ data: [] })
    vi.mocked(api.notifications).mockResolvedValue({ data: [], unread: 0 })

    renderTeamsRoute()

    expect(await screen.findByText('Teams page content')).toBeInTheDocument()
    expect(screen.getByText('New chat')).toBeInTheDocument()
    expect(screen.getByText('Résumé Match')).toBeInTheDocument()
  })
})

describe('Layout — the landing route and /account stay bare regardless of auth', () => {
  it('renders bare chrome for / with no search yet', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <AuthProvider>
          <Routes>
            <Route element={<Layout />}>
              <Route index element={<div>Landing content</div>} />
            </Route>
          </Routes>
        </AuthProvider>
      </MemoryRouter>,
    )
    expect(screen.getByText('Landing content')).toBeInTheDocument()
    expect(screen.queryByText('New chat')).not.toBeInTheDocument()
  })
})
