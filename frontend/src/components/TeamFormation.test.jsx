import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '../test/testUtils.jsx'
import TeamFormation from './TeamFormation'
import api from '../services/api'

vi.mock('../services/api', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    default: Object.fromEntries(Object.keys(actual.default).map((key) => [key, vi.fn()])),
  }
})

const member = (over) => ({
  user_id: null,
  name: 'Ada',
  source: 'profile',
  profile_status: 'complete',
  contributes: [{ skill: 'React', kind: 'technology', strength: 'solid', level: 'Advanced', source: 'profile' }],
  sole_holder_of: ['React'],
  suggested_role: { role: 'Frontend Developer', confidence: 'strong', score: 70 },
  ...over,
})

const team = (over = {}) => ({
  key: 'best_coverage',
  label: 'Best overall coverage',
  recommended: true,
  size: 2,
  members: [member(), member({ name: 'Ben', source: 'manual', profile_status: null, contributes: [{ skill: 'Node.js', kind: 'technology', strength: 'partial', level: null, source: 'past_project' }], sole_holder_of: [], suggested_role: null })],
  requirements: {
    solid: 1, partial: 1, uncovered: 1, total: 3,
    items: [
      { skill: 'React', kind: 'technology', status: 'solid', solid_by: ['Ada'], partial_by: [] },
      { skill: 'Node.js', kind: 'technology', status: 'partial', solid_by: [], partial_by: ['Ben'] },
      { skill: 'PostgreSQL', kind: 'technology', status: 'uncovered', solid_by: [], partial_by: [] },
    ],
  },
  roles: {
    needed_roles: [], plan: [], optional_roles: [],
    covered: [{ role: 'Frontend Developer', priority: true, primary: ['Ada'], could_also_cover: [] }],
    gaps: [{ role: 'Database Engineer', candidates: [], note: 'No one on the team lists skills that point to Database Engineer.' }],
    overlaps: [],
  },
  bottlenecks: [{ member: 'Ada', requirements: ['React'], note: 'Ada is the only person with solid evidence for 1 of the 1 solidly covered requirements.' }],
  explanation: 'Covers 1 of 3 requirements solidly and 1 partially; not covered: PostgreSQL. Ada brings React.',
  vs_individual_ranking: { covers_more: true, covers_same: false },
  ...over,
})

const result = (over = {}) => ({
  project: { project_id: 'pm-x', title: 'Campus Marketplace', domain: 'Web Development', difficulty: 'Intermediate' },
  requirements: { total: 3, limited: false },
  pool: { size: 2, matchable: 2, not_matched: [], coverage: { solid: 1, partial: 1, uncovered: ['PostgreSQL'], total: 3 } },
  objective: 'Teams are compared first by weighted requirement coverage.',
  teams: [
    team(),
    team({ key: 'top_individuals', label: 'Highest individual role scores (for comparison)', recommended: false, explanation: 'Shown only to compare.' }),
  ],
  limitations: ['Based on self-reported skills and the project’s listed requirements; nothing is verified.'],
  notes: ['No one in this pool covers: PostgreSQL. Consider recruiting someone with those skills.'],
  inputs: { team_size: 2, requested: null, source: 'default', default_rule: 'With no team size given, one person per main role.' },
  ...over,
})

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(api.me).mockResolvedValue({ data: { user_id: 'u1', email: 'a@b.co', name: 'Ada' } })
  vi.mocked(api.myTeams).mockResolvedValue({ data: [{ team_id: 't1', name: 'Marketplace crew' }] })
})

const signedIn = () => renderWithProviders(<TeamFormation projectId="pm-x" />, { authToken: 't' })
const submit = async (user) => user.click(await screen.findByRole('button', { name: 'Suggest teams' }))

describe('TeamFormation', () => {
  it('signed out: invites sign-in and makes no request', async () => {
    renderWithProviders(<TeamFormation projectId="pm-x" />)
    expect(await screen.findByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/account')
    expect(api.formTeams).not.toHaveBeenCalled()
    expect(api.myTeams).not.toHaveBeenCalled()
  })

  it('sends only what the user chose: project, self, team, size and typed people', async () => {
    const user = userEvent.setup()
    vi.mocked(api.formTeams).mockResolvedValue({ data: result() })
    signedIn()
    await screen.findByRole('option', { name: 'Marketplace crew' })
    await user.selectOptions(screen.getByLabelText('Use a team I’m in'), 't1')
    await user.selectOptions(screen.getByLabelText('Team size'), '3')
    await user.click(screen.getByRole('button', { name: 'Add a person' }))
    await user.type(screen.getByLabelText('Person 1 name'), 'Friend')
    await user.type(screen.getByLabelText('Person 1 skills'), 'react, , css ')
    await submit(user)
    await waitFor(() => expect(api.formTeams).toHaveBeenCalledTimes(1))
    expect(api.formTeams).toHaveBeenCalledWith({
      project_id: 'pm-x', include_self: true, team_id: 't1', team_size: 3,
      candidates: [{ name: 'Friend', skills: ['react', 'css'] }],
    })
  })

  it('shows loading and then the recommended team with contributions, coverage, roles and dependencies', async () => {
    const user = userEvent.setup()
    let resolve
    vi.mocked(api.formTeams).mockReturnValue(new Promise((r) => (resolve = r)))
    signedIn()
    await submit(user)
    expect(await screen.findByText(/comparing combinations/i)).toBeInTheDocument()
    resolve({ data: result() })

    const members = await screen.findByRole('list', { name: 'Team members' })
    expect(within(members).getByText('Ada')).toBeInTheDocument()
    expect(members).toHaveTextContent('React · advanced')
    expect(members).toHaveTextContent('Node.js · partial')
    expect(members).toHaveTextContent('Only person here with solid evidence for: React.')
    expect(screen.getByLabelText('Requirement coverage')).toHaveTextContent('1 of 3 requirements solid · 1 partial · 1 not covered')
    expect(screen.getByLabelText('Requirement coverage')).toHaveTextContent('Not covered: PostgreSQL')
    expect(screen.getByLabelText('Role coverage')).toHaveTextContent('No owner · Database Engineer')
    expect(screen.getByLabelText('Single-person dependencies')).toHaveTextContent('Dependency · Ada is the only person')
    expect(screen.getByText(/consider recruiting someone/i)).toBeInTheDocument()
  })

  it('lets the user switch between alternatives, and marks the comparison team as not a recommendation', async () => {
    const user = userEvent.setup()
    vi.mocked(api.formTeams).mockResolvedValue({ data: result() })
    signedIn()
    await submit(user)
    const group = await screen.findByRole('radiogroup', { name: 'Suggested teams' })
    expect(within(group).getByRole('radio', { name: 'Best overall coverage' })).toHaveAttribute('aria-checked', 'true')
    expect(screen.queryByText(/for comparison only/i)).not.toBeInTheDocument()
    await user.click(within(group).getByRole('radio', { name: /highest individual role scores/i }))
    expect(screen.getByText(/for comparison only — not a recommendation/i)).toBeInTheDocument()
    expect(within(group).getByRole('radio', { name: /highest individual/i })).toHaveAttribute('aria-checked', 'true')
  })

  it('makes clear nothing was created, and the next step is the user’s own existing workflow', async () => {
    const user = userEvent.setup()
    vi.mocked(api.formTeams).mockResolvedValue({ data: result() })
    signedIn()
    await submit(user)
    expect(await screen.findByText('Nothing has been created, invited or changed.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /start a team workspace below/i })).toHaveAttribute('href', '#start-team')
    expect(api.createTeam).not.toHaveBeenCalled()
  })

  it('with a chosen team the next step links to that team', async () => {
    const user = userEvent.setup()
    vi.mocked(api.formTeams).mockResolvedValue({ data: result() })
    signedIn()
    await screen.findByRole('option', { name: 'Marketplace crew' })
    await user.selectOptions(screen.getByLabelText('Use a team I’m in'), 't1')
    await submit(user)
    expect(await screen.findByRole('link', { name: 'open your team' })).toHaveAttribute('href', '/teams/t1')
  })

  it('warns about incomplete profiles and unmatched people without treating them as lacking skills', async () => {
    const user = userEvent.setup()
    const res = result({ pool: { size: 3, matchable: 2, not_matched: [{ name: 'Quiet', source: 'none', reason: 'x' }], coverage: { solid: 1, partial: 0, uncovered: [], total: 3 } } })
    res.teams[0].members[0] = member({ profile_status: 'in_progress' })
    vi.mocked(api.formTeams).mockResolvedValue({ data: res })
    signedIn()
    await submit(user)
    expect(await screen.findByText(/profile incomplete — their skills may be under-counted/i)).toBeInTheDocument()
    expect(screen.getByText(/not matched: quiet — no skills on file\. that does not mean they lack skills/i)).toBeInTheDocument()
  })

  it('project with no requirements and empty pools show explanatory empty states', async () => {
    const user = userEvent.setup()
    vi.mocked(api.formTeams).mockResolvedValueOnce({ data: result({ teams: [], requirements: { total: 0, limited: true }, notes: [] }) })
    const { unmount } = signedIn()
    await submit(user)
    expect(await screen.findByText(/lists no requirements, so there is nothing to build a team around/i)).toBeInTheDocument()
    unmount()

    vi.mocked(api.formTeams).mockResolvedValueOnce({ data: result({ teams: [], notes: ['None of the candidates has skills on file, so no team can be recommended.'] }) })
    signedIn()
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Suggest teams' }))
    expect(await screen.findByText(/no team can be suggested from this pool yet/i)).toBeInTheDocument()
  })

  it('sparse requirements are flagged as loosely specific', async () => {
    const user = userEvent.setup()
    vi.mocked(api.formTeams).mockResolvedValue({ data: result({ requirements: { total: 1, limited: true } }) })
    signedIn()
    await submit(user)
    expect(await screen.findByText(/only loosely project-specific/i)).toBeInTheDocument()
  })

  it('requires at least one candidate before calling the server', async () => {
    const user = userEvent.setup()
    signedIn()
    await user.click(await screen.findByLabelText('Include me'))
    await submit(user)
    expect(await screen.findByText(/choose at least one candidate/i)).toBeInTheDocument()
    expect(api.formTeams).not.toHaveBeenCalled()
  })

  it('shows server errors with a retry that re-runs the request', async () => {
    const user = userEvent.setup()
    vi.mocked(api.formTeams).mockRejectedValueOnce(new Error('No team found, or you are not a member.')).mockResolvedValueOnce({ data: result() })
    signedIn()
    await submit(user)
    expect(await screen.findByText('No team found, or you are not a member.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('list', { name: 'Team members' })).toBeInTheDocument()
    expect(api.formTeams).toHaveBeenCalledTimes(2)
  })

  it('documents assumptions and the selection rule, and claims no percentages', async () => {
    const user = userEvent.setup()
    vi.mocked(api.formTeams).mockResolvedValue({ data: result() })
    signedIn()
    await submit(user)
    expect(await screen.findByText('How teams are chosen, and what this assumes')).toBeInTheDocument()
    expect(screen.getByText(/nothing is verified/i)).toBeInTheDocument()
    expect(screen.queryByText(/%/)).not.toBeInTheDocument()
  })
})
