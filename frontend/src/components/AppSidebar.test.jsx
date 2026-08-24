import { describe, expect, it, vi, beforeEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import { renderWithProviders } from '../test/testUtils.jsx'
import AppSidebar from './AppSidebar'
import api from '../services/api'

// Only the default-exported `api` object's methods are mocked (real network
// calls) — the named exports (getAuthToken/setAuthToken/getDeviceId/...)
// stay real, since hooks/useAuth.jsx relies on their genuine localStorage
// behaviour to decide signed-in state. A blanket `vi.mock('../services/api')`
// automock replaces those too, silently breaking every "signed in" scenario
// (getAuthToken() always returns undefined regardless of localStorage).
vi.mock('../services/api', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    default: Object.fromEntries(Object.keys(actual.default).map((key) => [key, vi.fn()])),
  }
})

beforeEach(() => {
  window.localStorage.clear()
  vi.mocked(api.me).mockReset()
  vi.mocked(api.listConversations).mockReset()
})

describe('AppSidebar — signed out', () => {
  it('shows a sign-in prompt instead of any conversation list', async () => {
    renderWithProviders(<AppSidebar />)
    expect(await screen.findByText(/sign in to see your chat history/i)).toBeInTheDocument()
    expect(api.listConversations).not.toHaveBeenCalled()
  })
})

describe('AppSidebar — signed in', () => {
  const SIGNED_IN_USER = { user_id: 'u1', name: 'Alex', email: 'alex@example.com' }

  function signIn() {
    vi.mocked(api.me).mockResolvedValue({ data: SIGNED_IN_USER })
  }

  it('shows a loading state before the conversation list resolves', async () => {
    signIn()
    let resolveConversations
    vi.mocked(api.listConversations).mockReturnValue(
      new Promise((resolve) => {
        resolveConversations = resolve
      }),
    )

    renderWithProviders(<AppSidebar />, { authToken: 'tok-1' })

    expect(await screen.findByText(/loading/i)).toBeInTheDocument()
    resolveConversations({ data: [] })
  })

  it('shows an empty state when there are no conversations yet', async () => {
    signIn()
    vi.mocked(api.listConversations).mockResolvedValue({ data: [] })

    renderWithProviders(<AppSidebar />, { authToken: 'tok-1' })

    expect(await screen.findByText(/no conversations yet/i)).toBeInTheDocument()
  })

  it('lists the signed-in user\'s real conversations', async () => {
    signIn()
    vi.mocked(api.listConversations).mockResolvedValue({
      data: [
        { conversation_id: 'c1', title: 'NLP project ideas' },
        { conversation_id: 'c2', title: 'Blockchain roadmap' },
      ],
    })

    renderWithProviders(<AppSidebar />, { authToken: 'tok-1' })

    expect(await screen.findByText('NLP project ideas')).toBeInTheDocument()
    expect(screen.getByText('Blockchain roadmap')).toBeInTheDocument()
  })

  it('shows a visible error state when the conversation list fails to load', async () => {
    signIn()
    vi.mocked(api.listConversations).mockRejectedValue(new Error('network down'))

    renderWithProviders(<AppSidebar />, { authToken: 'tok-1' })

    // Regression test for the known bug: AppSidebar sets status('error') on
    // a failed fetch, but previously had no render branch for it at all —
    // the list just silently stayed empty with no feedback. A real error
    // state must say something, not render nothing.
    await waitFor(() => expect(api.listConversations).toHaveBeenCalled())
    expect(await screen.findByText(/couldn.t load your conversations/i)).toBeInTheDocument()
  })
})
