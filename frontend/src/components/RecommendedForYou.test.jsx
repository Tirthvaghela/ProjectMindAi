import { describe, expect, it, vi, beforeEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '../test/testUtils.jsx'
import RecommendedForYou from './RecommendedForYou'
import api from '../services/api'

vi.mock('../services/api', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    default: Object.fromEntries(Object.keys(actual.default).map((key) => [key, vi.fn()])),
  }
})

const project = (id, title, difficulty, weeks) => ({
  project_id: id,
  title,
  description: `${title} description`,
  domain: 'Machine Learning',
  difficulty,
  duration_weeks: weeks,
  technologies: ['Python'],
  relevance: { score: 0.8, matched_terms: [] },
  overall_score: 80,
  matching_factors: [],
  recommendation_reason: `Reason for ${title}.`,
})

const BEGINNER_RESULTS = { data: [project('b1', 'Starter Classifier', 'Beginner', 5)], diagnostics: null }
const ADVANCED_RESULTS = { data: [project('a1', 'Research Pipeline', 'Advanced', 10)], diagnostics: null }

function deferred() {
  let resolve, reject
  const promise = new Promise((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

async function openPanel(user) {
  renderWithProviders(<RecommendedForYou isFavorite={() => false} onToggleFavorite={() => {}} />)
  await user.click(screen.getByRole('button', { name: /best fit for you/i }))
  await screen.findByLabelText('Your skills')
}

const submit = (user) => user.click(screen.getByRole('button', { name: /find my best fit/i }))

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(api.filters).mockResolvedValue({ data: { difficulties: ['Beginner', 'Intermediate', 'Advanced'] } })
})

describe('Best fit for you — request payload', () => {
  it('sends the latest skills, experience, team size and max weeks', async () => {
    vi.mocked(api.recommend).mockResolvedValue(BEGINNER_RESULTS)
    const user = userEvent.setup()
    await openPanel(user)

    await user.type(screen.getByLabelText('Your skills'), ' Python ,  React,, pandas ')
    await screen.findByRole('option', { name: 'Advanced' })
    await user.selectOptions(screen.getByLabelText('Experience'), 'Advanced')
    const team = screen.getByLabelText('Team size')
    await user.clear(team)
    await user.type(team, '3')
    await user.type(screen.getByLabelText('Max weeks'), '8')
    await submit(user)

    await waitFor(() => expect(api.recommend).toHaveBeenCalledTimes(1))
    expect(api.recommend).toHaveBeenCalledWith({
      known_skills: ['Python', 'React', 'pandas'],
      experience_level: 'Advanced',
      team_size: 3,
      max_duration_weeks: 8,
      top_k: 6,
    })
  })

  it('omits experience and the week limit when they are left on Any', async () => {
    vi.mocked(api.recommend).mockResolvedValue(BEGINNER_RESULTS)
    const user = userEvent.setup()
    await openPanel(user)
    await user.type(screen.getByLabelText('Your skills'), 'Python')
    await submit(user)

    await waitFor(() => expect(api.recommend).toHaveBeenCalled())
    const payload = vi.mocked(api.recommend).mock.calls[0][0]
    expect(payload.experience_level).toBeUndefined()
    expect(payload.max_duration_weeks).toBeUndefined()
  })

  it('submits from the keyboard (Enter in the skills field)', async () => {
    vi.mocked(api.recommend).mockResolvedValue(BEGINNER_RESULTS)
    const user = userEvent.setup()
    await openPanel(user)
    await user.type(screen.getByLabelText('Your skills'), 'Python{Enter}')
    await waitFor(() => expect(api.recommend).toHaveBeenCalledTimes(1))
  })
})

describe('Best fit for you — changing only the experience level', () => {
  it('sends the new level on the next submit and replaces the cards', async () => {
    vi.mocked(api.recommend).mockResolvedValueOnce(BEGINNER_RESULTS).mockResolvedValueOnce(ADVANCED_RESULTS)
    const user = userEvent.setup()
    await openPanel(user)
    await user.type(screen.getByLabelText('Your skills'), 'Python')
    await screen.findByRole('option', { name: 'Beginner' })

    await user.selectOptions(screen.getByLabelText('Experience'), 'Beginner')
    await submit(user)
    expect(await screen.findByText('Starter Classifier')).toBeInTheDocument()

    await user.selectOptions(screen.getByLabelText('Experience'), 'Advanced')
    await submit(user)
    expect(await screen.findByText('Research Pipeline')).toBeInTheDocument()

    expect(screen.queryByText('Starter Classifier')).not.toBeInTheDocument()
    const [first, second] = vi.mocked(api.recommend).mock.calls.map((c) => c[0])
    expect(first.experience_level).toBe('Beginner')
    expect(second.experience_level).toBe('Advanced')
    expect({ ...first, experience_level: null }).toEqual({ ...second, experience_level: null })
  })

  it('flags results as out of date as soon as an input changes, until resubmitted', async () => {
    vi.mocked(api.recommend).mockResolvedValue(BEGINNER_RESULTS)
    const user = userEvent.setup()
    await openPanel(user)
    await user.type(screen.getByLabelText('Your skills'), 'Python')
    await submit(user)
    await screen.findByText('Starter Classifier')
    expect(screen.queryByText(/results are for the previous request/i)).not.toBeInTheDocument()

    await screen.findByRole('option', { name: 'Advanced' })
    await user.selectOptions(screen.getByLabelText('Experience'), 'Advanced')
    expect(screen.getByText(/results are for the previous request/i)).toBeInTheDocument()

    await submit(user)
    await waitFor(() => expect(screen.queryByText(/results are for the previous request/i)).not.toBeInTheDocument())
  })

  it('labels the results with the inputs they were computed from', async () => {
    vi.mocked(api.recommend).mockResolvedValue(BEGINNER_RESULTS)
    const user = userEvent.setup()
    await openPanel(user)
    await user.type(screen.getByLabelText('Your skills'), 'Python')
    await screen.findByRole('option', { name: 'Advanced' })
    await user.selectOptions(screen.getByLabelText('Experience'), 'Advanced')
    await user.type(screen.getByLabelText('Max weeks'), '6')
    await submit(user)
    expect(await screen.findByText(/Results for Advanced · team of 1 · up to 6 weeks/)).toBeInTheDocument()
  })
})

describe('Best fit for you — loading, duplicates, errors, empty', () => {
  it('shows a loading state, disables the button and does not fire a second request', async () => {
    const pending = deferred()
    vi.mocked(api.recommend).mockReturnValue(pending.promise)
    const user = userEvent.setup()
    await openPanel(user)
    await user.type(screen.getByLabelText('Your skills'), 'Python')
    await submit(user)

    const button = await screen.findByRole('button', { name: /ranking/i })
    expect(button).toBeDisabled()
    expect(screen.getByText(/ranking the catalogue/i)).toBeInTheDocument()
    await user.click(button)
    await user.type(screen.getByLabelText('Your skills'), '{Enter}')
    expect(api.recommend).toHaveBeenCalledTimes(1)

    pending.resolve(BEGINNER_RESULTS)
    expect(await screen.findByText('Starter Classifier')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /find my best fit/i })).toBeEnabled()
  })

  it('shows the server error and no stale cards', async () => {
    vi.mocked(api.recommend).mockResolvedValueOnce(BEGINNER_RESULTS).mockRejectedValueOnce(new Error('Server exploded.'))
    const user = userEvent.setup()
    await openPanel(user)
    await user.type(screen.getByLabelText('Your skills'), 'Python')
    await submit(user)
    await screen.findByText('Starter Classifier')

    await submit(user)
    expect(await screen.findByRole('alert')).toHaveTextContent('Server exploded.')
    expect(screen.queryByText('Starter Classifier')).not.toBeInTheDocument()
  })

  it('requires at least one skill and never calls the API without one', async () => {
    const user = userEvent.setup()
    await openPanel(user)
    await user.type(screen.getByLabelText('Your skills'), ' , ,')
    await submit(user)
    expect(await screen.findByRole('alert')).toHaveTextContent(/at least one skill/i)
    expect(api.recommend).not.toHaveBeenCalled()
  })

  it.each([['0'], ['-4'], ['2.5'], ['99']])('rejects max weeks %s before sending anything', async (weeks) => {
    const user = userEvent.setup()
    await openPanel(user)
    await user.type(screen.getByLabelText('Your skills'), 'Python')
    await user.type(screen.getByLabelText('Max weeks'), weeks)
    await submit(user)
    expect(await screen.findByRole('alert')).toHaveTextContent(/max weeks/i)
    expect(api.recommend).not.toHaveBeenCalled()
  })

  it('explains an empty result with the real shortest estimate when a deadline was set', async () => {
    vi.mocked(api.recommend).mockResolvedValue({
      data: [],
      diagnostics: { max_duration_weeks: 2, shortest_estimated_weeks: 3.5 },
    })
    const user = userEvent.setup()
    await openPanel(user)
    await user.type(screen.getByLabelText('Your skills'), 'Python')
    await user.type(screen.getByLabelText('Max weeks'), '2')
    await submit(user)

    expect(await screen.findByText(/Nothing fits within 2 weeks for a team of 1/)).toBeInTheDocument()
    expect(screen.getByText(/about 3.5 weeks/)).toBeInTheDocument()
  })

  it('says plainly when nothing matched and no deadline was involved', async () => {
    vi.mocked(api.recommend).mockResolvedValue({ data: [], diagnostics: null })
    const user = userEvent.setup()
    await openPanel(user)
    await user.type(screen.getByLabelText('Your skills'), 'Cobol')
    await submit(user)
    expect(await screen.findByText(/No projects matched those skills/)).toBeInTheDocument()
  })

  it('recovers from a failed request and shows the next successful result', async () => {
    const slow = deferred()
    vi.mocked(api.recommend).mockReturnValueOnce(slow.promise).mockResolvedValueOnce(ADVANCED_RESULTS)
    const user = userEvent.setup()
    await openPanel(user)
    await user.type(screen.getByLabelText('Your skills'), 'Python')
    await submit(user) // request 1, still pending
    slow.reject(new Error('timeout'))
    await screen.findByRole('alert')
    await submit(user)
    expect(await screen.findByText('Research Pipeline')).toBeInTheDocument()
  })
})

describe('Best fit for you — unknown durations', () => {
  it('says how many projects a week limit left out because their duration is unknown', async () => {
    vi.mocked(api.recommend).mockResolvedValue({ ...BEGINNER_RESULTS, excluded_unknown_duration: 3 })
    const user = userEvent.setup()
    await openPanel(user)
    await user.type(screen.getByLabelText('Your skills'), 'Python')
    await user.type(screen.getByLabelText('Max weeks'), '6')
    await submit(user)
    expect(await screen.findByText(/3 projects with no documented duration were left out/)).toBeInTheDocument()
  })

  it('shows no such note when nothing was left out or no limit was set', async () => {
    vi.mocked(api.recommend).mockResolvedValue({ ...BEGINNER_RESULTS, excluded_unknown_duration: null })
    const user = userEvent.setup()
    await openPanel(user)
    await user.type(screen.getByLabelText('Your skills'), 'Python')
    await submit(user)
    await screen.findByText('Starter Classifier')
    expect(screen.queryByText(/no documented duration/)).not.toBeInTheDocument()
  })
})

const PROFILE = {
  skills: [{ name: 'React', level: 'Intermediate', recognised: true }],
  interests: ['Web Development'],
  experience: [],
  availability: { hours_per_week: 6, max_project_weeks: 10 },
  updated_at: '2026-01-01T00:00:00',
  completion: { status: 'in_progress', percent: 50, missing: [] },
}
const EMPTY_PROFILE = {
  skills: [],
  interests: [],
  experience: [],
  availability: { hours_per_week: null, max_project_weeks: null },
  updated_at: null,
  completion: { status: 'not_started', percent: 0, missing: [] },
}
const APPLIED = {
  requested: true,
  applied: true,
  reason: 'applied',
  skills_from_profile: 1,
  skills_from_request: 0,
  interests: ['Web Development'],
  experience_level: 'Beginner',
  experience_level_source: 'profile_skill_levels',
  preferred_weeks: 10,
  hours_per_week: 6,
}

async function openSignedIn(user, profile) {
  vi.mocked(api.me).mockResolvedValue({ data: { user_id: 'u1', email: 'a@b.co', name: 'Ada' } })
  vi.mocked(api.learnerProfile).mockResolvedValue({ data: profile })
  renderWithProviders(<RecommendedForYou isFavorite={() => false} onToggleFavorite={() => {}} />, { authToken: 't' })
  await user.click(screen.getByRole('button', { name: /best fit for you/i }))
}

describe('Best fit for you — saved profile', () => {
  beforeEach(() => window.localStorage.clear())

  it('signed out: no profile controls and no use_profile flag', async () => {
    vi.mocked(api.recommend).mockResolvedValue(BEGINNER_RESULTS)
    const user = userEvent.setup()
    await openPanel(user)
    expect(screen.queryByLabelText(/use my saved profile/i)).not.toBeInTheDocument()
    await user.type(screen.getByLabelText('Your skills'), 'Python')
    await submit(user)
    await waitFor(() => expect(api.recommend).toHaveBeenCalled())
    expect(vi.mocked(api.recommend).mock.calls[0][0]).not.toHaveProperty('use_profile')
    expect(api.learnerProfile).not.toHaveBeenCalled()
  })

  it('uses the profile by default, so typing skills is optional, and says so', async () => {
    vi.mocked(api.recommend).mockResolvedValue({ ...BEGINNER_RESULTS, personalization: APPLIED })
    const user = userEvent.setup()
    await openSignedIn(user, PROFILE)
    expect(await screen.findByLabelText(/use my saved profile/i)).toBeChecked()
    expect(screen.getByLabelText(/extra skills for this search \(optional\)/i)).toBeInTheDocument()

    await submit(user)
    await waitFor(() => expect(api.recommend).toHaveBeenCalledTimes(1))
    expect(vi.mocked(api.recommend).mock.calls[0][0]).toMatchObject({ known_skills: [], use_profile: true })
    expect(await screen.findByText(/personalised with your profile: 1 skill, 1 interest/i)).toBeInTheDocument()
    expect(screen.getByText(/estimated from your own skill ratings/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Edit profile' })).toHaveAttribute('href', '/profile')
  })

  it('switching the profile off restores the plain, skills-required behaviour', async () => {
    vi.mocked(api.recommend).mockResolvedValue(BEGINNER_RESULTS)
    const user = userEvent.setup()
    await openSignedIn(user, PROFILE)
    await user.click(await screen.findByLabelText(/use my saved profile/i))

    await submit(user)
    expect(await screen.findByRole('alert')).toHaveTextContent(/add at least one skill/i)
    expect(api.recommend).not.toHaveBeenCalled()

    await user.type(screen.getByLabelText('Your skills'), 'Python')
    await submit(user)
    await waitFor(() => expect(api.recommend).toHaveBeenCalledTimes(1))
    expect(vi.mocked(api.recommend).mock.calls[0][0]).not.toHaveProperty('use_profile')
  })

  it('an account with no profile is invited to add one, never blocked', async () => {
    vi.mocked(api.recommend).mockResolvedValue(BEGINNER_RESULTS)
    const user = userEvent.setup()
    await openSignedIn(user, EMPTY_PROFILE)
    expect(await screen.findByRole('link', { name: /add your skills and interests/i })).toHaveAttribute('href', '/profile?setup=1')
    expect(screen.queryByLabelText(/use my saved profile/i)).not.toBeInTheDocument()

    await user.type(screen.getByLabelText('Your skills'), 'Python')
    await submit(user)
    await waitFor(() => expect(api.recommend).toHaveBeenCalledTimes(1))
    expect(vi.mocked(api.recommend).mock.calls[0][0]).not.toHaveProperty('use_profile')
  })

  it('explains when the server could not apply the profile', async () => {
    vi.mocked(api.recommend).mockResolvedValue({ ...BEGINNER_RESULTS, personalization: { requested: true, applied: false, reason: 'sign_in_required' } })
    const user = userEvent.setup()
    await openSignedIn(user, PROFILE)
    await submit(user)
    expect(await screen.findByText(/sign in to use your saved profile/i)).toBeInTheDocument()
  })
})
