import { describe, expect, it, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '../test/testUtils.jsx'
import Ideate from './Ideate'
import api from '../services/api'

vi.mock('../services/api', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    default: Object.fromEntries(Object.keys(actual.default).map((key) => [key, vi.fn()])),
  }
})

const GENERATED_IDEA = {
  id: 'idea-1',
  name: 'StudyStream',
  problem: 'Students lose track of scattered lecture notes across apps.',
  solution: 'A single searchable hub that summarizes and links notes automatically.',
  unique_point: 'Summarizes using only on-device, open-source models.',
  technologies: ['Python', 'FastAPI'],
  domain: 'Natural Language Processing',
  difficulty: 'Intermediate',
  duration_weeks: 8,
  originality_score: 88,
}

function signIn() {
  window.localStorage.setItem('projectmind.authToken', 'tok-1')
  vi.mocked(api.me).mockResolvedValue({ data: { user_id: 'u1', name: 'Alex', email: 'alex@example.com' } })
}

beforeEach(() => {
  window.localStorage.clear()
  vi.mocked(api.filters).mockResolvedValue({ data: { domains: [], difficulties: [] } })
})

describe('Ideate — idle state', () => {
  it('shows the empty state before anything is generated', async () => {
    signIn()
    renderWithProviders(<Ideate />, { route: '/ideate' })
    expect(await screen.findByText('Describe an idea to get started')).toBeInTheDocument()
  })
})

describe('Ideate — generating an idea', () => {
  it('sends the described concept and renders the generated idea card', async () => {
    signIn()
    vi.mocked(api.createConversation).mockResolvedValue({ data: { conversation_id: 'c1' } })
    vi.mocked(api.sendConversationMessage).mockResolvedValue({
      data: {
        reply: "Here's a new idea for you.",
        blocks: [{ type: 'generated_project_ideas', ideas: [GENERATED_IDEA] }],
      },
    })

    const user = userEvent.setup()
    renderWithProviders(<Ideate />, { route: '/ideate' })

    const topic = screen.getByLabelText(/project concept/i)
    await user.type(topic, 'An NLP tool for organizing lecture notes')
    await user.click(screen.getByRole('button', { name: /generate blueprints/i }))

    expect(await screen.findByText('StudyStream')).toBeInTheDocument()
    expect(api.sendConversationMessage).toHaveBeenCalledWith(
      'c1',
      expect.stringContaining('An NLP tool for organizing lecture notes'),
    )
  })

  it('shows a loading state while the idea is being generated', async () => {
    signIn()
    vi.mocked(api.createConversation).mockResolvedValue({ data: { conversation_id: 'c1' } })
    let resolveSend
    vi.mocked(api.sendConversationMessage).mockReturnValue(
      new Promise((resolve) => {
        resolveSend = resolve
      }),
    )

    const user = userEvent.setup()
    renderWithProviders(<Ideate />, { route: '/ideate' })
    await user.click(screen.getByRole('button', { name: /generate blueprints/i }))

    expect(await screen.findByText(/thinking up original project concepts/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /thinking/i })).toBeDisabled()

    resolveSend({ data: { reply: '', blocks: [{ type: 'generated_project_ideas', ideas: [GENERATED_IDEA] }] } })
    await screen.findByText('StudyStream')
  })
})

describe('Ideate — error handling', () => {
  it('shows an error message when generation fails outright', async () => {
    signIn()
    vi.mocked(api.createConversation).mockResolvedValue({ data: { conversation_id: 'c1' } })
    vi.mocked(api.sendConversationMessage).mockRejectedValue(new Error('The AI assistant could not respond right now — try again.'))

    const user = userEvent.setup()
    renderWithProviders(<Ideate />, { route: '/ideate' })
    await user.click(screen.getByRole('button', { name: /generate blueprints/i }))

    // Shown in two places at once by design — the sidebar's own inline
    // error line and the main panel's ErrorNotice — both carrying the same
    // message.
    const matches = await screen.findAllByText('The AI assistant could not respond right now — try again.')
    expect(matches.length).toBeGreaterThan(0)
  })

  it('shows a fallback message when the reply carries no ideas block', async () => {
    signIn()
    vi.mocked(api.createConversation).mockResolvedValue({ data: { conversation_id: 'c1' } })
    vi.mocked(api.sendConversationMessage).mockResolvedValue({
      data: { reply: '', blocks: [] },
    })

    const user = userEvent.setup()
    renderWithProviders(<Ideate />, { route: '/ideate' })
    await user.click(screen.getByRole('button', { name: /generate blueprints/i }))

    const matches = await screen.findAllByText(/no ideas came back/i)
    expect(matches.length).toBeGreaterThan(0)
  })
})
