import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '../test/testUtils.jsx'
import Profile from './Profile'
import ProfilePrompt from '../components/ProfilePrompt'
import api from '../services/api'

vi.mock('../services/api', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    default: Object.fromEntries(Object.keys(actual.default).map((key) => [key, vi.fn()])),
  }
})

const OPTIONS = {
  proficiency_levels: ['Beginner', 'Intermediate', 'Advanced'],
  domains: ['Robotics', 'Web Development'],
  team_roles: ['Frontend Developer', 'Backend Developer'],
  limits: { skills: 50, skill_chars: 60, experience: 10, goals: 10, goal_chars: 200, career: 10, hours_per_week: 80, max_project_weeks: 52 },
}

function profileWith(overrides = {}, completion) {
  return {
    skills: [],
    interests: [],
    experience: [],
    learning_goals: [],
    career_interests: [],
    preferred_roles: [],
    availability: { hours_per_week: null, max_project_weeks: null },
    education: '',
    onboarding_dismissed: false,
    created_at: null,
    updated_at: null,
    completion: completion || { status: 'not_started', percent: 0, missing: [{ key: 'skills', label: 'Skills', core: true }] },
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  window.localStorage.clear()
  vi.mocked(api.me).mockResolvedValue({ data: { user_id: 'u1', email: 'a@b.co', name: 'Ada' } })
  vi.mocked(api.learnerProfileOptions).mockResolvedValue({ data: OPTIONS })
  vi.mocked(api.learnerProfile).mockResolvedValue({ data: profileWith() })
})

describe('Profile page', () => {
  it('asks signed-out visitors to sign in and fetches nothing private', async () => {
    renderWithProviders(<Profile />)
    expect(await screen.findByText(/sign in to build your profile/i)).toBeInTheDocument()
    expect(api.learnerProfile).not.toHaveBeenCalled()
  })

  it('shows an empty-state friendly form for an existing account with no profile', async () => {
    renderWithProviders(<Profile />, { authToken: 't' })
    expect(await screen.findByRole('heading', { name: 'Your profile' })).toBeInTheDocument()
    expect(screen.getByText(/no skills yet/i)).toBeInTheDocument()
    expect(screen.getByRole('progressbar', { name: /profile completion/i })).toHaveAttribute('aria-valuenow', '0')
  })

  it('adds a skill with a level and saves only what the API accepts', async () => {
    const user = userEvent.setup()
    vi.mocked(api.saveLearnerProfile).mockResolvedValue({
      data: profileWith({ skills: [{ name: 'React', level: 'Advanced', recognised: true }] }, { status: 'in_progress', percent: 17, missing: [] }),
    })
    renderWithProviders(<Profile />, { authToken: 't' })
    await screen.findByRole('heading', { name: 'Your profile' })

    await user.type(screen.getByPlaceholderText(/e\.g\. React/i), 'reactjs')
    await user.selectOptions(screen.getAllByRole('combobox')[0], 'Advanced')
    await user.click(screen.getByRole('button', { name: 'Add skill' }))
    expect(screen.getByRole('list', { name: 'Your skills' })).toHaveTextContent('reactjs')

    await user.click(screen.getByRole('button', { name: 'Save profile' }))
    await waitFor(() => expect(api.saveLearnerProfile).toHaveBeenCalled())
    const payload = vi.mocked(api.saveLearnerProfile).mock.calls[0][0]
    expect(payload.skills).toEqual([{ name: 'reactjs', level: 'Advanced' }]) // no `recognised`, normalised server-side
    expect(Object.keys(payload)).not.toContain('onboarding_dismissed')
    expect(await screen.findByText('Saved.')).toBeInTheDocument()
    expect(screen.getByRole('list', { name: 'Your skills' })).toHaveTextContent('React')
  })

  it('shows the server validation message and keeps what the user typed', async () => {
    const user = userEvent.setup()
    vi.mocked(api.saveLearnerProfile).mockRejectedValue(new Error('Hours per week must be between 1 and 80.'))
    renderWithProviders(<Profile />, { authToken: 't' })
    await screen.findByRole('heading', { name: 'Your profile' })

    await user.type(screen.getByRole('textbox', { name: 'Education' }), 'BSc CS')
    await user.click(screen.getByRole('button', { name: 'Save profile' }))
    expect(await screen.findByText(/hours per week must be between/i)).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: 'Education' })).toHaveValue('BSc CS')
  })

  it('toggles interests and roles as pressed buttons', async () => {
    const user = userEvent.setup()
    renderWithProviders(<Profile />, { authToken: 't' })
    await screen.findByRole('heading', { name: 'Your profile' })
    const robotics = screen.getByRole('button', { name: 'Robotics' })
    expect(robotics).toHaveAttribute('aria-pressed', 'false')
    await user.click(robotics)
    expect(robotics).toHaveAttribute('aria-pressed', 'true')
  })

  it('setup mode walks through steps, saving each, and can be skipped or dismissed', async () => {
    const user = userEvent.setup()
    vi.mocked(api.saveLearnerProfile).mockResolvedValue({ data: profileWith() })
    renderWithProviders(<Profile />, { authToken: 't', route: '/profile?setup=1' })

    expect(await screen.findByText(/step 1 of 4/i)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Save and continue' }))
    await waitFor(() => expect(api.saveLearnerProfile).toHaveBeenCalledWith({ skills: [] }))
    expect(await screen.findByText(/step 2 of 4/i)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Skip this step' }))
    expect(await screen.findByText(/step 3 of 4/i)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Not now' }))
    await waitFor(() => expect(api.saveLearnerProfile).toHaveBeenLastCalledWith({ onboarding_dismissed: true }))
  })

  it('requires confirmation before deleting profile data', async () => {
    const user = userEvent.setup()
    vi.mocked(api.deleteLearnerProfile).mockResolvedValue({ data: { deleted: true } })
    renderWithProviders(<Profile />, { authToken: 't' })
    await screen.findByRole('heading', { name: 'Your profile' })

    await user.click(screen.getByRole('button', { name: /delete profile…/i }))
    expect(api.deleteLearnerProfile).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: /yes, delete profile/i }))
    await waitFor(() => expect(api.deleteLearnerProfile).toHaveBeenCalledTimes(1))
  })

  it('reports a load failure with a retry', async () => {
    vi.mocked(api.learnerProfile).mockRejectedValueOnce(new Error('boom'))
    renderWithProviders(<Profile />, { authToken: 't' })
    expect(await screen.findByText('boom')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })
})

describe('ProfilePrompt', () => {
  it('invites a not-started account once, without blocking', async () => {
    renderWithProviders(<ProfilePrompt />, { authToken: 't', route: '/dashboard' })
    expect(await screen.findByRole('region', { name: /complete your profile/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Set up profile' })).toHaveAttribute('href', '/profile?setup=1')
  })

  it('stays hidden when complete, dismissed, signed out, or on the profile page', async () => {
    vi.mocked(api.learnerProfile).mockResolvedValue({ data: profileWith({}, { status: 'complete', percent: 83, missing: [] }) })
    const { unmount } = renderWithProviders(<ProfilePrompt />, { authToken: 't', route: '/dashboard' })
    await waitFor(() => expect(api.learnerProfile).toHaveBeenCalled())
    expect(screen.queryByRole('region', { name: /complete your profile/i })).not.toBeInTheDocument()
    unmount()

    vi.mocked(api.learnerProfile).mockResolvedValue({ data: profileWith({ onboarding_dismissed: true }) })
    const second = renderWithProviders(<ProfilePrompt />, { authToken: 't', route: '/dashboard' })
    await waitFor(() => expect(api.learnerProfile).toHaveBeenCalledTimes(2))
    expect(screen.queryByRole('region', { name: /complete your profile/i })).not.toBeInTheDocument()
    second.unmount()

    vi.mocked(api.learnerProfile).mockClear()
    renderWithProviders(<ProfilePrompt />, { route: '/dashboard' })
    expect(screen.queryByRole('region', { name: /complete your profile/i })).not.toBeInTheDocument()
    expect(api.learnerProfile).not.toHaveBeenCalled()
  })

  it('"Not now" hides it immediately and persists the choice', async () => {
    const user = userEvent.setup()
    vi.mocked(api.saveLearnerProfile).mockResolvedValue({ data: profileWith({ onboarding_dismissed: true }) })
    renderWithProviders(<ProfilePrompt />, { authToken: 't', route: '/dashboard' })
    await user.click(await screen.findByRole('button', { name: 'Not now' }))
    expect(screen.queryByRole('region', { name: /complete your profile/i })).not.toBeInTheDocument()
    expect(api.saveLearnerProfile).toHaveBeenCalledWith({ onboarding_dismissed: true })
  })
})

describe('Profile sharing setting', () => {
  it('is off by default, explained, and saved on its own through the profile API', async () => {
    const user = userEvent.setup()
    vi.mocked(api.saveLearnerProfile).mockResolvedValue({ data: profileWith({ share_with_teams: true }) })
    renderWithProviders(<Profile />, { authToken: 't' })
    const box = await screen.findByRole('checkbox', { name: /let my teammates use my relevant skills/i })
    expect(box).not.toBeChecked()
    expect(screen.getByText(/never shown/i)).toBeInTheDocument()
    expect(screen.getByText(/does not erase anything a teammate has already seen/i)).toBeInTheDocument()

    await user.click(box)
    await waitFor(() => expect(api.saveLearnerProfile).toHaveBeenCalledWith({ share_with_teams: true }))
    expect(await screen.findByText('Sharing is on.')).toBeInTheDocument()
    expect(box).toBeChecked()
  })

  it('turning it off sends only the setting and says sharing stops going forward', async () => {
    const user = userEvent.setup()
    vi.mocked(api.learnerProfile).mockResolvedValue({ data: profileWith({ share_with_teams: true }) })
    vi.mocked(api.saveLearnerProfile).mockResolvedValue({ data: profileWith({ share_with_teams: false }) })
    renderWithProviders(<Profile />, { authToken: 't' })
    const box = await screen.findByRole('checkbox', { name: /let my teammates/i })
    expect(box).toBeChecked()
    await user.click(box)
    await waitFor(() => expect(api.saveLearnerProfile).toHaveBeenCalledWith({ share_with_teams: false }))
    expect(await screen.findByText('Sharing is off.')).toBeInTheDocument()
    expect(box).not.toBeChecked()
  })

  it('shows a failure and keeps the previous state', async () => {
    const user = userEvent.setup()
    vi.mocked(api.saveLearnerProfile).mockRejectedValue(new Error('Network down'))
    renderWithProviders(<Profile />, { authToken: 't' })
    const box = await screen.findByRole('checkbox', { name: /let my teammates/i })
    await user.click(box)
    expect(await screen.findByRole('alert')).toHaveTextContent('Network down')
    expect(box).not.toBeChecked()
  })

  it('is not part of the setup wizard', async () => {
    renderWithProviders(<Profile />, { authToken: 't', route: '/profile?setup=1' })
    await screen.findByText(/step 1 of 4/i)
    expect(screen.queryByRole('checkbox', { name: /let my teammates/i })).not.toBeInTheDocument()
  })
})
