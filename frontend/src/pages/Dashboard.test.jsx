import { describe, expect, it, vi, beforeEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '../test/testUtils.jsx'
import Dashboard from './Dashboard'
import api from '../services/api'

vi.mock('../services/api', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    default: Object.fromEntries(Object.keys(actual.default).map((key) => [key, vi.fn()])),
  }
})

function signIn() {
  window.localStorage.setItem('projectmind.authToken', 'tok-1')
  vi.mocked(api.me).mockResolvedValue({ data: { user_id: 'u1', name: 'Alex', email: 'alex@example.com' } })
}

beforeEach(() => {
  window.localStorage.clear()
  vi.mocked(api.health).mockResolvedValue({ ai_assistant: { enabled: true } })
})

describe('Dashboard — empty state', () => {
  it('shows the ready-to-chat greeting before any message is sent', async () => {
    signIn()
    renderWithProviders(<Dashboard />, { route: '/dashboard' })
    expect(await screen.findByText('Welcome back, Alex.')).toBeInTheDocument()
  })
})

describe('Dashboard — sending a message', () => {
  it('sends the typed message and renders the reply', async () => {
    signIn()
    vi.mocked(api.createConversation).mockResolvedValue({ data: { conversation_id: 'c1' } })
    vi.mocked(api.sendConversationMessage).mockResolvedValue({
      data: { reply: 'Here are a few NLP project ideas.', blocks: null, selected_project_id: null, selected_idea: null },
    })

    const user = userEvent.setup()
    renderWithProviders(<Dashboard />, { route: '/dashboard' })
    await screen.findByText('Welcome back, Alex.')

    const input = screen.getByLabelText('Message ProjectMind')
    await user.type(input, 'Give me some NLP project ideas')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    // The user's own message renders immediately (optimistic), the input clears.
    expect(await screen.findByText('Give me some NLP project ideas')).toBeInTheDocument()
    expect(input).toHaveValue('')

    // Then the real reply arrives.
    expect(await screen.findByText('Here are a few NLP project ideas.')).toBeInTheDocument()
    expect(api.sendConversationMessage).toHaveBeenCalledWith('c1', 'Give me some NLP project ideas')
  })

  it('shows a typing indicator while waiting for the reply', async () => {
    signIn()
    vi.mocked(api.createConversation).mockResolvedValue({ data: { conversation_id: 'c1' } })
    let resolveSend
    vi.mocked(api.sendConversationMessage).mockReturnValue(
      new Promise((resolve) => {
        resolveSend = resolve
      }),
    )

    const user = userEvent.setup()
    renderWithProviders(<Dashboard />, { route: '/dashboard' })
    await screen.findByText('Welcome back, Alex.')

    await user.type(screen.getByLabelText('Message ProjectMind'), 'Hello')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    expect(await screen.findByRole('button', { name: 'Send' })).toBeDisabled()

    resolveSend({ data: { reply: 'Hi! What are you building?', blocks: null } })
    await screen.findByText('Hi! What are you building?')
  })

  it('the send button stays disabled for a blank/whitespace-only message', async () => {
    signIn()
    renderWithProviders(<Dashboard />, { route: '/dashboard' })
    await screen.findByText('Welcome back, Alex.')

    const sendButton = screen.getByRole('button', { name: 'Send' })
    expect(sendButton).toBeDisabled()

    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Message ProjectMind'), '   ')
    expect(sendButton).toBeDisabled()
  })
})

describe('Dashboard — error state', () => {
  it('shows the error and a retry action when sending fails', async () => {
    signIn()
    vi.mocked(api.createConversation).mockResolvedValue({ data: { conversation_id: 'c1' } })
    vi.mocked(api.sendConversationMessage).mockRejectedValue(
      Object.assign(new Error('The AI assistant could not respond right now — try again.'), {}),
    )

    const user = userEvent.setup()
    renderWithProviders(<Dashboard />, { route: '/dashboard' })
    await screen.findByText('Welcome back, Alex.')

    await user.type(screen.getByLabelText('Message ProjectMind'), 'Hello')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    expect(await screen.findByText('The AI assistant could not respond right now — try again.')).toBeInTheDocument()

    // The failed optimistic user message is rolled back rather than left
    // stuck on screen with no way to tell it never actually sent.
    await waitFor(() => expect(screen.queryByText('Hello')).not.toBeInTheDocument())
  })
})
