import { describe, expect, it, vi, beforeEach } from 'vitest'
import { screen, within } from '@testing-library/react'
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

const GROUNDING = {
  type: 'grounding',
  sources: [
    { kind: 'profile', label: 'Your saved profile' },
    { kind: 'roadmap', label: 'Your roadmap and saved progress for “Campus Marketplace”' },
  ],
  follow_ups: ['What should I do first?', 'Which step should I tackle next?'],
}

beforeEach(() => {
  vi.resetAllMocks()
  window.localStorage.clear()
  vi.mocked(api.health).mockResolvedValue({ ai_assistant: { enabled: true } })
  vi.mocked(api.createConversation).mockResolvedValue({ data: { conversation_id: 'c1' } })
})

async function ask(user, text) {
  await screen.findByText('Welcome back, Alex.')
  await user.type(screen.getByLabelText('Message ProjectMind'), text)
  await user.click(screen.getByRole('button', { name: 'Send' }))
}

describe('Dashboard — personal assistant grounding', () => {
  it('shows which saved ProjectMind data an answer used, from the server block', async () => {
    signIn()
    vi.mocked(api.sendConversationMessage).mockResolvedValue({
      data: { reply: 'You have 2 of 5 steps completed.', blocks: [GROUNDING], selected_project_id: null, selected_idea: null },
    })
    const user = userEvent.setup()
    renderWithProviders(<Dashboard />, { route: '/dashboard' })
    await ask(user, 'How far along am I?')

    expect(await screen.findByText('You have 2 of 5 steps completed.')).toBeInTheDocument()
    const used = await screen.findByLabelText('Data used for this answer')
    expect(within(used).getByText('Your saved profile')).toBeInTheDocument()
    expect(within(used).getByText(/saved progress for “Campus Marketplace”/)).toBeInTheDocument()
  })

  it('a follow-up suggestion sends through the existing chat pipeline', async () => {
    signIn()
    vi.mocked(api.sendConversationMessage)
      .mockResolvedValueOnce({ data: { reply: 'Here is your roadmap.', blocks: [GROUNDING], selected_project_id: null, selected_idea: null } })
      .mockResolvedValueOnce({ data: { reply: 'Start with Python.', blocks: null, selected_project_id: null, selected_idea: null } })
    const user = userEvent.setup()
    renderWithProviders(<Dashboard />, { route: '/dashboard' })
    await ask(user, 'Show my roadmap')

    const followUps = await screen.findByLabelText('Suggested follow-up questions')
    await user.click(within(followUps).getByRole('button', { name: 'What should I do first?' }))
    expect(await screen.findByText('Start with Python.')).toBeInTheDocument()
    expect(api.sendConversationMessage).toHaveBeenLastCalledWith('c1', 'What should I do first?')
  })

  it('answers without a grounding block show no data-used label', async () => {
    signIn()
    vi.mocked(api.sendConversationMessage).mockResolvedValue({
      data: { reply: 'A closure captures variables from its scope.', blocks: null, selected_project_id: null, selected_idea: null },
    })
    const user = userEvent.setup()
    renderWithProviders(<Dashboard />, { route: '/dashboard' })
    await ask(user, 'What is a closure?')
    expect(await screen.findByText('A closure captures variables from its scope.')).toBeInTheDocument()
    expect(screen.queryByLabelText('Data used for this answer')).not.toBeInTheDocument()
  })

  it('a provider failure shows an error with Retry, and retry then shows the grounded answer', async () => {
    signIn()
    const failure = Object.assign(new Error('The assistant is temporarily unavailable.'), { serverCode: 'LLM_UNAVAILABLE' })
    vi.mocked(api.sendConversationMessage)
      .mockRejectedValueOnce(failure)
      .mockResolvedValueOnce({ data: { reply: 'Recovered answer.', blocks: [GROUNDING], selected_project_id: null, selected_idea: null } })
    const user = userEvent.setup()
    renderWithProviders(<Dashboard />, { route: '/dashboard' })
    await ask(user, 'Show my roadmap')

    await user.click(await screen.findByRole('button', { name: 'Retry' }))
    expect(await screen.findByText('Recovered answer.')).toBeInTheDocument()
    expect(await screen.findByLabelText('Data used for this answer')).toBeInTheDocument()
  })

  it('follow-up buttons are not offered on a user message', async () => {
    signIn()
    vi.mocked(api.sendConversationMessage).mockResolvedValue({
      data: { reply: 'ok', blocks: [GROUNDING], selected_project_id: null, selected_idea: null },
    })
    const user = userEvent.setup()
    renderWithProviders(<Dashboard />, { route: '/dashboard' })
    await ask(user, 'hello')
    await screen.findByLabelText('Data used for this answer')
    expect(screen.getAllByLabelText('Data used for this answer')).toHaveLength(1)
  })
})
