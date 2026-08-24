import { describe, expect, it, vi, beforeEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '../test/testUtils.jsx'
import Search from './Search'
import api from '../services/api'

vi.mock('../services/api', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    default: Object.fromEntries(Object.keys(actual.default).map((key) => [key, vi.fn()])),
  }
})

const PROJECT = {
  project_id: 'pm-001',
  title: 'Campus Study Buddy Matcher',
  difficulty: 'Beginner',
  domain: 'Natural Language Processing',
  duration_weeks: 6,
  description: 'Matches students into study groups using semantic similarity of their course notes.',
  technologies: ['Python', 'Flask'],
}

// Rendering with `?q=...` already in the URL skips the pure landing state
// (LandingHero, which pulls in a WebGL/three.js background jsdom can't
// render) and goes straight to the searched view — real, load-bearing app
// behaviour (hasSearched = Boolean(urlQuery)), not a test-only shortcut.
const SEARCHED_ROUTE = '/?q=nlp+project'

beforeEach(() => {
  window.localStorage.clear()
  vi.mocked(api.listFavorites).mockResolvedValue({ data: [] })
  vi.mocked(api.filters).mockResolvedValue({
    data: {
      domains: ['Natural Language Processing', 'Web Development'],
      difficulties: ['Beginner', 'Intermediate', 'Advanced'],
      technologies: ['Python', 'Flask'],
    },
  })
})

describe('Search — results', () => {
  it('renders the returned projects with the query and count', async () => {
    vi.mocked(api.search).mockResolvedValue({
      data: [PROJECT],
      query: 'nlp project',
      count: 1,
      personalization: { applied: false },
    })

    renderWithProviders(<Search />, { route: SEARCHED_ROUTE })

    expect(await screen.findByText('Campus Study Buddy Matcher')).toBeInTheDocument()
    expect(screen.getByText('1')).toBeInTheDocument()
    expect(screen.getByText(/nlp project/)).toBeInTheDocument()
    expect(api.search).toHaveBeenCalledWith(expect.objectContaining({ query: 'nlp project' }))
  })

  it('shows the searching state before results arrive', async () => {
    let resolveSearch
    vi.mocked(api.search).mockReturnValue(
      new Promise((resolve) => {
        resolveSearch = resolve
      }),
    )
    renderWithProviders(<Search />, { route: SEARCHED_ROUTE })

    expect(await screen.findByText('Searching project catalogue')).toBeInTheDocument()
    resolveSearch({ data: [], query: 'nlp project', count: 0, personalization: { applied: false } })
  })

  it('shows a no-results state for a genuinely empty result set', async () => {
    vi.mocked(api.search).mockResolvedValue({
      data: [],
      query: 'nlp project',
      count: 0,
      personalization: { applied: false },
    })
    renderWithProviders(<Search />, { route: SEARCHED_ROUTE })
    expect(await screen.findByText('No close matches found.')).toBeInTheDocument()
  })
})

describe('Search — error state', () => {
  it('shows an error with a retry action when the search request fails', async () => {
    vi.mocked(api.search).mockRejectedValue(new Error('The server could not be reached.'))
    renderWithProviders(<Search />, { route: SEARCHED_ROUTE })

    expect(await screen.findByText('The server could not be reached.')).toBeInTheDocument()

    vi.mocked(api.search).mockResolvedValue({
      data: [PROJECT],
      query: 'nlp project',
      count: 1,
      personalization: { applied: false },
    })
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: /retry|try again/i }))
    expect(await screen.findByText('Campus Study Buddy Matcher')).toBeInTheDocument()
  })
})

describe('Search — filters', () => {
  it('re-runs the search with the selected domain filter applied', async () => {
    vi.mocked(api.search).mockResolvedValue({
      data: [PROJECT],
      query: 'nlp project',
      count: 1,
      personalization: { applied: false },
    })
    const user = userEvent.setup()
    renderWithProviders(<Search />, { route: SEARCHED_ROUTE })
    await screen.findByText('Campus Study Buddy Matcher')

    // Both the desktop FilterPanel and the (CSS-hidden but still mounted)
    // mobile drawer render their own copy — pick the first, real one.
    const [domainSelect] = screen.getAllByLabelText(/domain/i)
    await user.selectOptions(domainSelect, 'Natural Language Processing')

    await waitFor(() =>
      expect(api.search).toHaveBeenLastCalledWith(
        expect.objectContaining({ domain: 'Natural Language Processing' }),
      ),
    )
  })
})
