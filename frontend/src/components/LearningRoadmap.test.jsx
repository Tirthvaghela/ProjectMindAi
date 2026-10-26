import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '../test/testUtils.jsx'
import LearningRoadmap from './LearningRoadmap'
import api from '../services/api'

vi.mock('../services/api', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    default: Object.fromEntries(Object.keys(actual.default).map((key) => [key, vi.fn()])),
  }
})

const step = (over) => {
  const row = {
    id: 's-python',
    number: 1,
    kind: 'prerequisite',
    skill: 'Python',
    skills: ['Python'],
    classification: 'missing',
    evidence: { source: 'none', skill: null, level: null, self_reported: false },
    from_project_requirements: false,
    priority: null,
    why_it_matters: 'Flask is built on Python.',
    why_for_you: 'Python is not on your profile, and Flask builds on it.',
    prerequisites: [],
    practice_task: 'Complete an official Python tutorial, then write a small working example on your own.',
    completion_criterion: 'You can write a small working Python example without copying.',
    resources: [{ platform: 'Python docs', title: 'Official Python documentation', url: 'https://docs.python.org/3/tutorial/' }],
    matches_your_goal: null,
    after: { id: 's-flask', skill: 'Flask' },
    status: 'not_started',
    ...over,
  }
  return row
}

const roadmap = (over = {}) => ({
  project: { project_id: 'pm-x', title: 'Campus Marketplace', domain: 'Web Development', difficulty: 'Intermediate' },
  profile: { status: 'in_progress', percent: 40, has_skills: true, skills_listed: 1, past_project_technologies: 0 },
  requirements: { total: 3, limited: false },
  overview: { steps: 2, by_kind: {}, already_covered: ['React'], domain_interest: false, finish: 'When these steps feel solid, start building “Campus Marketplace”.' },
  steps: [
    step(),
    step({
      id: 's-flask', number: 2, kind: 'learn', skill: 'Flask', from_project_requirements: true,
      why_it_matters: '“Campus Marketplace” is built with Flask.', why_for_you: 'Flask is not on your profile.',
      prerequisites: [{ skill: 'Python', status: 'in_roadmap' }], matches_your_goal: 'Get comfortable with Flask',
      resources: [], after: null,
    }),
  ],
  ordering: { basis: 'x', known_prerequisite_edges: 1, cycle_detected: false, reliable: true, note: 'Steps follow the standard order and the listed prerequisites.' },
  notes: [],
  progress: { not_started: 2, in_progress: 0, completed: 0, total: 2 },
  retired_steps: [],
  disclaimer: 'A suggested order, not a guarantee of project success.',
  ...over,
})

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(api.me).mockResolvedValue({ data: { user_id: 'u1', email: 'a@b.co', name: 'Ada' } })
})

const signedIn = () => renderWithProviders(<LearningRoadmap projectId="pm-x" />, { authToken: 't' })

describe('LearningRoadmap', () => {
  it('signed out: invites sign-in and makes no request', async () => {
    renderWithProviders(<LearningRoadmap projectId="pm-x" />)
    expect(await screen.findByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/account')
    expect(api.personalRoadmap).not.toHaveBeenCalled()
  })

  it('shows a loading state and then the ordered steps with why, prerequisites, practice and done-when', async () => {
    let resolve
    vi.mocked(api.personalRoadmap).mockReturnValue(new Promise((r) => (resolve = r)))
    signedIn()
    expect(await screen.findByText(/building your roadmap/i)).toBeInTheDocument()
    resolve({ data: roadmap() })

    const list = await screen.findByRole('list', { name: 'Learning steps' })
    const items = within(list).getAllByRole('listitem')
    expect(items).toHaveLength(2)
    expect(items[0]).toHaveTextContent('1. Python')
    expect(items[0]).toHaveTextContent('Foundation · not listed by the project')
    expect(items[0]).toHaveTextContent('Done when You can write a small working Python example')
    expect(items[1]).toHaveTextContent('Before this: Python (earlier step)')
    expect(items[1]).toHaveTextContent('Matches your goal: “Get comfortable with Flask”')
    expect(within(items[0]).getByRole('link', { name: 'Python docs' })).toHaveAttribute('href', 'https://docs.python.org/3/tutorial/')
    expect(items[0]).toHaveTextContent('Next: Flask')
    expect(api.personalRoadmap).toHaveBeenCalledWith('pm-x')
  })

  it('summarises progress as a real count, never a percentage, and lists skipped skills', async () => {
    vi.mocked(api.personalRoadmap).mockResolvedValue({ data: roadmap({ progress: { not_started: 1, in_progress: 0, completed: 1, total: 2 } }) })
    signedIn()
    expect(await screen.findByLabelText('Progress')).toHaveTextContent('1 of 2 steps completed')
    expect(screen.getByText(/skipped because your profile already covers them: React/i)).toBeInTheDocument()
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Progress')).not.toHaveTextContent('%') // the profile notice may show profile completion; progress never does
    expect(screen.queryByText(/\b(hours|weeks|days)\b/i)).not.toBeInTheDocument()
  })

  it('changing a status calls the API and shows the saved result', async () => {
    const user = userEvent.setup()
    vi.mocked(api.personalRoadmap).mockResolvedValue({ data: roadmap() })
    const updated = roadmap({ progress: { not_started: 1, in_progress: 1, completed: 0, total: 2 } })
    updated.steps[0].status = 'in_progress'
    vi.mocked(api.setRoadmapStep).mockResolvedValue({ data: updated })
    signedIn()

    const group = await screen.findByRole('group', { name: /status of step 1: python/i })
    await user.click(within(group).getByRole('button', { name: 'In progress' }))
    expect(api.setRoadmapStep).toHaveBeenCalledWith('pm-x', 's-python', 'in_progress')
    await waitFor(() => expect(within(screen.getByRole('group', { name: /step 1/i })).getByRole('button', { name: 'In progress' })).toHaveAttribute('aria-pressed', 'true'))
    expect(screen.getByLabelText('Progress')).toHaveTextContent('1 in progress')
  })

  it('completing a step does not touch the profile and only offers an explicit link', async () => {
    const user = userEvent.setup()
    const done = roadmap({ progress: { not_started: 1, in_progress: 0, completed: 1, total: 2 } })
    done.steps[0].status = 'completed'
    vi.mocked(api.personalRoadmap).mockResolvedValue({ data: roadmap() })
    vi.mocked(api.setRoadmapStep).mockResolvedValue({ data: done })
    signedIn()
    const group = await screen.findByRole('group', { name: /step 1/i })
    await user.click(within(group).getByRole('button', { name: 'Completed' }))
    expect(await screen.findByText(/completing a step does not change your profile/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /add or update python yourself/i })).toHaveAttribute('href', '/profile')
    expect(api.saveLearnerProfile).not.toHaveBeenCalled()
  })

  it('a failed update is reported and the previous state is kept', async () => {
    const user = userEvent.setup()
    vi.mocked(api.personalRoadmap).mockResolvedValue({ data: roadmap() })
    vi.mocked(api.setRoadmapStep).mockRejectedValue(new Error('No step in this roadmap.'))
    signedIn()
    const group = await screen.findByRole('group', { name: /step 1/i })
    await user.click(within(group).getByRole('button', { name: 'In progress' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('No step in this roadmap.')
    expect(within(screen.getByRole('group', { name: /step 1/i })).getByRole('button', { name: 'Not started' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('reset needs confirmation and then calls the API', async () => {
    const user = userEvent.setup()
    const withProgress = roadmap({ progress: { not_started: 1, in_progress: 0, completed: 1, total: 2 } })
    withProgress.steps[0].status = 'completed'
    vi.mocked(api.personalRoadmap).mockResolvedValue({ data: withProgress })
    vi.mocked(api.resetRoadmap).mockResolvedValue({ data: { reset: true, roadmap: roadmap() } })
    signedIn()

    await user.click(await screen.findByRole('button', { name: /reset progress/i }))
    expect(api.resetRoadmap).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(api.resetRoadmap).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: /reset progress/i }))
    expect(screen.getByRole('alertdialog')).toHaveTextContent('cannot be undone')
    await user.click(screen.getByRole('button', { name: /yes, reset progress/i }))
    await waitFor(() => expect(api.resetRoadmap).toHaveBeenCalledWith('pm-x'))
    expect(await screen.findByLabelText('Progress')).toHaveTextContent('0 of 2 steps completed')
  })

  it('no reset control until there is something to reset', async () => {
    vi.mocked(api.personalRoadmap).mockResolvedValue({ data: roadmap() })
    signedIn()
    await screen.findByRole('list', { name: 'Learning steps' })
    expect(screen.queryByRole('button', { name: /reset progress/i })).not.toBeInTheDocument()
  })

  it('incomplete profile: shows a limited-personalisation notice with a link', async () => {
    vi.mocked(api.personalRoadmap).mockResolvedValue({ data: roadmap() })
    signedIn()
    expect(await screen.findByText(/your profile is 40% complete/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Update your profile' })).toHaveAttribute('href', '/profile?setup=1')
  })

  it('no profile: starts from the basics and offers to add one', async () => {
    vi.mocked(api.personalRoadmap).mockResolvedValue({ data: roadmap({ profile: { status: 'not_started', percent: 0, has_skills: false, skills_listed: 0, past_project_technologies: 0 } }) })
    signedIn()
    expect(await screen.findByText(/starts from the basics/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Add your profile' })).toBeInTheDocument()
  })

  it('empty roadmap: explains nothing is needed, or that the project lists no requirements', async () => {
    vi.mocked(api.personalRoadmap).mockResolvedValueOnce({ data: roadmap({ steps: [], progress: { not_started: 0, in_progress: 0, completed: 0, total: 0 }, overview: { steps: 0, by_kind: {}, already_covered: [], finish: 'You can start building “Campus Marketplace” on what your profile lists.' } }) })
    const { unmount } = signedIn()
    expect(await screen.findByText(/you can start building/i)).toBeInTheDocument()
    expect(screen.queryByRole('list', { name: 'Learning steps' })).not.toBeInTheDocument()
    unmount()

    vi.mocked(api.personalRoadmap).mockResolvedValueOnce({ data: roadmap({ steps: [], requirements: { total: 0, limited: true }, progress: { not_started: 0, in_progress: 0, completed: 0, total: 0 } }) })
    signedIn()
    expect(await screen.findByText(/no listed requirements to build a roadmap from/i)).toBeInTheDocument()
  })

  it('retired steps are mentioned, not silently dropped', async () => {
    vi.mocked(api.personalRoadmap).mockResolvedValue({ data: roadmap({ retired_steps: [{ id: 's-react', label: 'React', status: 'completed' }] }) })
    signedIn()
    expect(await screen.findByText(/earlier steps no longer needed for your current profile: React \(completed\)/i)).toBeInTheDocument()
  })

  it('error state offers a retry', async () => {
    const user = userEvent.setup()
    vi.mocked(api.personalRoadmap).mockRejectedValueOnce(new Error('No project with id pm-x.')).mockResolvedValueOnce({ data: roadmap() })
    signedIn()
    expect(await screen.findByText('No project with id pm-x.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('list', { name: 'Learning steps' })).toBeInTheDocument()
  })

  it('states that the order is a heuristic and the roadmap is not a guarantee', async () => {
    vi.mocked(api.personalRoadmap).mockResolvedValue({ data: roadmap() })
    signedIn()
    expect(await screen.findByText(/not a guarantee of project success/i)).toBeInTheDocument()
    expect(screen.getByText('How the order is decided')).toBeInTheDocument()
  })
})
