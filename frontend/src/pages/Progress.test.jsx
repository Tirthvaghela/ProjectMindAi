import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '../test/testUtils.jsx'
import Progress from './Progress'
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

const HISTORY = { available: false, note: 'ProjectMind does not keep a log of earlier changes, so past progress cannot be shown.' }

const EMPTY = {
  profile: { status: 'not_started', completion_percent: 0, missing_sections: ['Skills'], skill_count: 0, level_counts: { Beginner: 0, Intermediate: 0, Advanced: 0 } },
  profile_skills: [],
  learning: { started: false, projects_with_progress: 0, projects_unavailable: 0, projects_truncated: false, totals: { completed: 0, in_progress: 0, remaining: 0, total_steps: 0 }, retired_recorded_steps: 0, projects: [], skills_worked_on: [], recent_activity: [] },
  profile_review: [],
  next_steps: { items: [{ type: 'profile', reason: 'Your profile is missing sections.', missing_sections: ['Skills'], link: '/profile' }] },
  history: HISTORY,
  disclaimer: 'Declared levels are self-reported.',
}

const FULL = {
  profile: { status: 'in_progress', completion_percent: 40, missing_sections: ['Time available'], skill_count: 2, level_counts: { Beginner: 1, Intermediate: 1, Advanced: 0 } },
  profile_skills: [
    { name: 'Python', declared_level: 'Intermediate', recorded_progress: 'none', recognised: true },
    { name: 'React', declared_level: 'Beginner', recorded_progress: 'completed', recognised: true },
  ],
  learning: {
    started: true, projects_with_progress: 1, projects_unavailable: 1, projects_truncated: false,
    totals: { completed: 1, in_progress: 1, remaining: 3, total_steps: 5 }, retired_recorded_steps: 2,
    projects: [{ project_id: 'pm-1', title: 'Campus Marketplace', total_steps: 5, completed: 1, in_progress: 1, remaining: 3 }],
    skills_worked_on: [
      { skill: 'React', recorded_status: 'completed', on_profile: true, declared_level: 'Beginner' },
      { skill: 'Docker', recorded_status: 'in_progress', on_profile: false, declared_level: null },
    ],
    recent_activity: [
      { skill: 'React', status: 'completed', project_id: 'pm-1', project_title: 'Campus Marketplace', status_set_at: '2026-03-04T10:00:00+00:00', earlier_step: false },
      { skill: 'Docker', status: 'in_progress', project_id: 'pm-1', project_title: 'Campus Marketplace', status_set_at: null, earlier_step: false },
    ],
  },
  profile_review: [{ skill: 'React', declared_level: 'Beginner', reason: 'You completed a step for this skill; your profile still lists it as Beginner.' }],
  next_steps: {
    items: [
      { type: 'roadmap_step', project_id: 'pm-1', project_title: 'Campus Marketplace', step_id: 'docker', skill: 'Docker', kind: 'learn', status: 'in_progress', reason: 'You marked this step in progress.', link: '/project/pm-1' },
      { type: 'profile', reason: 'Your profile is missing sections.', missing_sections: ['Time available'], link: '/profile' },
    ],
  },
  history: HISTORY,
  disclaimer: 'Declared levels are self-reported.',
}

beforeEach(() => {
  vi.resetAllMocks()
  window.localStorage.clear()
})

describe('Progress page', () => {
  it('asks signed-out visitors to sign in and fetches nothing', async () => {
    vi.mocked(api.me).mockRejectedValue(new Error('no'))
    renderWithProviders(<Progress />, { route: '/progress' })
    expect(await screen.findByText('Sign in to see your progress')).toBeInTheDocument()
    expect(api.myInsights).not.toHaveBeenCalled()
  })

  it('shows a loading state, then honest empty states with navigation for a new account', async () => {
    signIn()
    vi.mocked(api.myInsights).mockResolvedValue({ data: EMPTY })
    renderWithProviders(<Progress />, { route: '/progress' })
    expect(screen.getByText('Loading your progress…')).toBeInTheDocument()

    expect(await screen.findByText(/You have not added a profile yet/)).toBeInTheDocument()
    expect(screen.getByText('You have not marked any roadmap steps yet.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Find a project' })).toHaveAttribute('href', '/search')
    expect(screen.getByRole('link', { name: 'Add your skills' })).toHaveAttribute('href', '/profile')
    const next = screen.getByLabelText('Suggested next steps')
    expect(within(next).getByRole('link', { name: 'Open profile' })).toHaveAttribute('href', '/profile')
    // No fabricated achievements or scores.
    expect(screen.queryByText(/%/)).not.toBeInTheDocument()
  })

  it('keeps declared levels and recorded progress separate and uses real persisted counts', async () => {
    signIn()
    vi.mocked(api.myInsights).mockResolvedValue({ data: FULL })
    renderWithProviders(<Progress />, { route: '/progress' })

    const profile = await screen.findByLabelText('Profile summary')
    expect(within(profile).getByText(/2 skills listed · profile 40% filled in/)).toBeInTheDocument()
    expect(within(profile).getByText(/self-reported/)).toBeInTheDocument()
    // React stays Beginner on the profile even though a step is completed.
    expect(within(within(profile).getByLabelText('Declared skills')).getByText(/React · Beginner/)).toBeInTheDocument()

    const learning = screen.getByLabelText('Recorded learning progress')
    expect(within(learning).getByText(/1 completed · 1 in progress · 3 not started, across 1 roadmap/)).toBeInTheDocument()
    expect(within(learning).getByRole('link', { name: 'Campus Marketplace' })).toHaveAttribute('href', '/project/pm-1')
    expect(within(learning).getByText(/1 of 5 completed · 1 in progress/)).toBeInTheDocument()
    expect(within(learning).getByText(/2 recorded steps no longer appear/)).toBeInTheDocument()
    expect(within(learning).getByText(/1 saved roadmap could not be read and is left out/)).toBeInTheDocument()
    expect(within(learning).getByText(/Docker · In progress/)).toBeInTheDocument()
    expect(within(learning).getByText(/not on profile/)).toBeInTheDocument()
  })

  it('shows dates only when recorded and never invents one', async () => {
    signIn()
    vi.mocked(api.myInsights).mockResolvedValue({ data: FULL })
    renderWithProviders(<Progress />, { route: '/progress' })
    const recent = await screen.findByLabelText('Recent step updates')
    const rows = within(recent).getAllByRole('listitem')
    expect(rows[0]).toHaveTextContent(/React — completed in “Campus Marketplace”/)
    expect(rows[0]).toHaveTextContent(/set Mar 4, 2026|set 4 Mar 2026|set 04\/03\/2026|set 3\/4\/2026/)
    expect(rows[1]).toHaveTextContent('date not recorded')
    expect(screen.getByText(/does not keep a log of earlier changes/)).toBeInTheDocument()
  })

  it('links next steps to the project and says suggestions are not done', async () => {
    signIn()
    vi.mocked(api.myInsights).mockResolvedValue({ data: FULL })
    renderWithProviders(<Progress />, { route: '/progress' })
    const next = await screen.findByLabelText('Suggested next steps')
    expect(within(next).getByText(/None of these is done until you mark it/)).toBeInTheDocument()
    expect(within(next).getByRole('link', { name: 'Open roadmap' })).toHaveAttribute('href', '/project/pm-1')
    expect(within(next).getByText(/Learn: Docker/)).toBeInTheDocument()
  })

  it('profile review prompts ask, never claim a level change', async () => {
    signIn()
    vi.mocked(api.myInsights).mockResolvedValue({ data: FULL })
    renderWithProviders(<Progress />, { route: '/progress' })
    const review = await screen.findByLabelText('Profile review')
    expect(within(review).getByText(/never changes your levels/)).toBeInTheDocument()
    expect(within(review).getByRole('link', { name: 'Review profile' })).toHaveAttribute('href', '/profile')
  })

  it('omits the review section when there is nothing to review', async () => {
    signIn()
    vi.mocked(api.myInsights).mockResolvedValue({ data: { ...FULL, profile_review: [] } })
    renderWithProviders(<Progress />, { route: '/progress' })
    await screen.findByLabelText('Profile summary')
    expect(screen.queryByLabelText('Profile review')).not.toBeInTheDocument()
  })

  it('shows an error with retry, and retry loads the data', async () => {
    signIn()
    vi.mocked(api.myInsights).mockRejectedValueOnce(new Error('Server hiccup')).mockResolvedValueOnce({ data: FULL })
    const user = userEvent.setup()
    renderWithProviders(<Progress />, { route: '/progress' })
    expect(await screen.findByText('Server hiccup')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByLabelText('Recorded learning progress')).toBeInTheDocument()
    expect(api.myInsights).toHaveBeenCalledTimes(2)
  })

  it('tells the user when only the most recent roadmaps are shown, and when all steps are underway', async () => {
    signIn()
    const done = { ...FULL, learning: { ...FULL.learning, projects_truncated: true }, next_steps: { items: [] } }
    vi.mocked(api.myInsights).mockResolvedValue({ data: done })
    renderWithProviders(<Progress />, { route: '/progress' })
    expect(await screen.findByText(/most recently updated roadmaps only/)).toBeInTheDocument()
    expect(screen.getByText(/Every step in your saved roadmaps is marked/)).toBeInTheDocument()
  })
})
