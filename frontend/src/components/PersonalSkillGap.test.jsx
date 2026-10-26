import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '../test/testUtils.jsx'
import PersonalSkillGap from './PersonalSkillGap'
import api from '../services/api'

vi.mock('../services/api', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    default: Object.fromEntries(Object.keys(actual.default).map((key) => [key, vi.fn()])),
  }
})

const item = (over) => withWhy({
  skill: 'PostgreSQL',
  kind: 'technology',
  mentions: 1,
  classification: 'missing',
  target_level: 'Intermediate',
  evidence: { source: 'none', skill: null, level: null, self_reported: false },
  recognised: true,
  priority: { level: 'high', reasons: ['It is part of the project’s own technology stack.'] },
  next_step: 'Work through an official PostgreSQL tutorial, then rebuild the Database Layer part of “Campus Marketplace”.',
  prerequisites: [],
  resources: [{ platform: 'PostgreSQL docs', title: 'Official PostgreSQL documentation', url: 'https://www.postgresql.org/docs/current/tutorial.html' }],
  ...over,
})

// Each fixture row explains itself with its own skill name, as the server does.
function withWhy(row) {
  return { ...row, why_it_matters: `“Campus Marketplace” is built with ${row.skill}.` }
}

const RULES = {
  bar: 'The catalogue records a project’s difficulty but no per-skill requirement.',
  classification: {},
  priority: { high: 'A stack technology you are missing.', medium: 'm', low: 'l' },
}

const result = (over = {}) => ({
  project: { project_id: 'pm-x', title: 'Campus Marketplace', domain: 'Web Development', difficulty: 'Intermediate' },
  profile: { status: 'in_progress', percent: 40, has_skills: true, skills_listed: 2, past_project_technologies: 0 },
  requirements: { total: 4, limited: false },
  summary: { have: 1, needs_improvement: 1, unclear: 1, missing: 1, total: 4 },
  items: [
    item(),
    item({ skill: 'React', classification: 'needs_improvement', evidence: { source: 'profile', skill: 'React', level: 'Beginner', self_reported: true }, priority: { level: 'medium', reasons: ['You rate it below the level this project’s difficulty suggests.'] }, next_step: 'You rate React as Beginner. Re-do the User Interface part.', resources: [] }),
    item({ skill: 'REST API development', kind: 'skill', classification: 'unclear', evidence: { source: 'related', skill: 'REST', level: null, self_reported: false }, priority: null, next_step: null, resources: [] }),
    item({ skill: 'Node.js', classification: 'have', evidence: { source: 'profile', skill: 'Node.js', level: 'Advanced', self_reported: true }, priority: null, next_step: null, resources: [] }),
  ],
  rules: RULES,
  ranking: { basis: 'rules', reliable: true, note: null },
  notes: [],
  disclaimer: 'Based on your self-reported profile and the project’s listed requirements. It is not a verified assessment.',
  ...over,
})

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(api.me).mockResolvedValue({ data: { user_id: 'u1', email: 'a@b.co', name: 'Ada' } })
})

const signedIn = () => renderWithProviders(<PersonalSkillGap projectId="pm-x" />, { authToken: 't' })

describe('PersonalSkillGap', () => {
  it('signed out: invites sign-in and makes no request', async () => {
    renderWithProviders(<PersonalSkillGap projectId="pm-x" />)
    expect(await screen.findByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/account')
    expect(api.personalSkillGap).not.toHaveBeenCalled()
  })

  it('shows a loading state, then the grouped results', async () => {
    let resolve
    vi.mocked(api.personalSkillGap).mockReturnValue(new Promise((r) => (resolve = r)))
    signedIn()
    expect(await screen.findByText(/comparing your profile/i)).toBeInTheDocument()
    resolve({ data: result() })

    expect(await screen.findByText(/1 covered · 1 to improve · 1 unclear · 1 not on your profile/)).toBeInTheDocument()
    expect(api.personalSkillGap).toHaveBeenCalledWith('pm-x')
    expect(screen.getByRole('region', { name: 'Worth working on' })).toHaveTextContent('PostgreSQL')
    expect(screen.getByRole('region', { name: 'Unclear' })).toHaveTextContent('Only a related skill is listed: REST (inferred, not confirmed)')
    expect(screen.getByRole('region', { name: 'Already covered' })).toHaveTextContent('Node.js — On your profile at Advanced (self-reported)')
  })

  it('shows priority, reason, why it matters, a concrete next step and a resource link', async () => {
    vi.mocked(api.personalSkillGap).mockResolvedValue({ data: result() })
    signedIn()
    expect(await screen.findByText('High priority')).toBeInTheDocument()
    expect(screen.getByText(/is built with PostgreSQL/)).toBeInTheDocument()
    expect(screen.getByText(/technology stack/)).toBeInTheDocument()
    expect(screen.getByText(/rebuild the Database Layer part/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'PostgreSQL docs' })).toHaveAttribute('href', 'https://www.postgresql.org/docs/current/tutorial.html')
    expect(screen.getByText(/You rate React as Beginner/)).toBeInTheDocument()
    expect(screen.getByText('Medium priority')).toBeInTheDocument()
  })

  it('never shows invented progress: no percentages of readiness, no estimates', async () => {
    vi.mocked(api.personalSkillGap).mockResolvedValue({ data: result() })
    signedIn()
    await screen.findByText(/1 covered/)
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
    expect(screen.queryByText(/% ready/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/weeks|hours/i)).not.toBeInTheDocument()
  })

  it('incomplete profile: shows a notice with a link to update it', async () => {
    vi.mocked(api.personalSkillGap).mockResolvedValue({ data: result() })
    signedIn()
    expect(await screen.findByText(/your profile is 40% complete/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Update your profile' })).toHaveAttribute('href', '/profile?setup=1')
  })

  it('no profile at all: says nothing was recorded, offers to add one', async () => {
    vi.mocked(api.personalSkillGap).mockResolvedValue({
      data: result({ profile: { status: 'not_started', percent: 0, has_skills: false, skills_listed: 0, past_project_technologies: 0 }, ranking: { basis: 'rules', reliable: false, note: 'Priorities are a simple ordering by learning sequence, not a reliable ranking.' } }),
    })
    signedIn()
    expect(await screen.findByText(/have not added any skills yet/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Add your profile' })).toBeInTheDocument()
    expect(screen.getByText(/not a reliable ranking/i)).toBeInTheDocument()
  })

  it('complete profile with nothing to improve shows only the covered group', async () => {
    vi.mocked(api.personalSkillGap).mockResolvedValue({
      data: result({
        profile: { status: 'complete', percent: 83, has_skills: true, skills_listed: 3, past_project_technologies: 0 },
        summary: { have: 1, needs_improvement: 0, unclear: 0, missing: 0, total: 1 },
        items: [result().items[3]],
      }),
    })
    signedIn()
    expect(await screen.findByRole('region', { name: 'Already covered' })).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Worth working on' })).not.toBeInTheDocument()
    expect(screen.queryByText(/your profile is .* complete/i)).not.toBeInTheDocument()
  })

  it('project with no requirement data explains the limit instead of listing gaps', async () => {
    vi.mocked(api.personalSkillGap).mockResolvedValue({
      data: result({ requirements: { total: 0, limited: true }, items: [], summary: { have: 0, needs_improvement: 0, unclear: 0, missing: 0, total: 0 }, notes: ['This project lists no skills or technologies, so there is nothing to compare your profile with.'] }),
    })
    signedIn()
    expect(await screen.findByText(/nothing to compare your profile with/i)).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Worth working on' })).not.toBeInTheDocument()
  })

  it('error state offers a retry that reloads', async () => {
    const user = userEvent.setup()
    vi.mocked(api.personalSkillGap).mockRejectedValueOnce(new Error('No project with id pm-x.')).mockResolvedValueOnce({ data: result() })
    signedIn()
    expect(await screen.findByText('No project with id pm-x.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    await waitFor(() => expect(api.personalSkillGap).toHaveBeenCalledTimes(2))
    expect(await screen.findByText(/1 covered/)).toBeInTheDocument()
  })

  it('explains the rules and the self-reported disclaimer', async () => {
    vi.mocked(api.personalSkillGap).mockResolvedValue({ data: result() })
    signedIn()
    expect(await screen.findByText(/not a verified assessment/i)).toBeInTheDocument()
    expect(screen.getByText('How this is decided')).toBeInTheDocument()
  })
})
