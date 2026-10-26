import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import RoleFitPanel from './RoleFitPanel'
import api from '../services/api'

vi.mock('../services/api', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    default: Object.fromEntries(Object.keys(actual.default).map((key) => [key, vi.fn()])),
  }
})

const suggestion = (role, extra = {}) => ({
  role,
  score: 72.4,
  confidence: 'strong',
  supporting_skills: [{ name: 'React', level: 'Advanced' }, { name: 'CSS', level: null }],
  missing_skills: ['Vue'],
  preferred: false,
  explanation: 'Their saved profile lists React (Advanced), which support Frontend Developer. Levels are self-reported.',
  ...extra,
})

const member = (overrides) => ({
  user_id: 'u1',
  name: 'Ada',
  source: 'profile',
  profile_status: 'complete',
  suggested: suggestion('Frontend Developer'),
  alternatives: [{ role: 'Full-Stack Developer', score: 55, confidence: 'moderate', supporting_skills: [] }],
  message: null,
  ...overrides,
})

const TEAM = {
  needed_roles: [
    { role: 'Frontend Developer', weight: 2, priority: true },
    { role: 'Backend Developer', weight: 2, priority: true },
    { role: 'DevOps Engineer', weight: 1, priority: false },
  ],
  covered: [{ role: 'Frontend Developer', priority: true, primary: ['Ada'], could_also_cover: [] }],
  gaps: [{ role: 'Backend Developer', candidates: [], note: 'No one on the team lists skills that point to Backend Developer.' }],
  overlaps: [],
  multi_role_members: [],
  plan: [{ member: 'Ada', user_id: 'u1', role: 'Frontend Developer', individual_role: 'Frontend Developer', differs: false, score: 72.4 }],
  optional_roles: ['DevOps Engineer'],
}

const result = (members, decisions = []) => ({
  role_fit: { score_meaning: 'x', has_project_requirements: true, members, team: TEAM },
  decisions,
})

function setup(res, userId = 'u1') {
  return render(
    <MemoryRouter>
      <RoleFitPanel result={res} userId={userId} teamId="t1" />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(api.learnerProfileOptions).mockResolvedValue({ data: { team_roles: ['Frontend Developer', 'QA / Test Engineer'] } })
})

describe('RoleFitPanel', () => {
  it('shows the role, heuristic score, supporting skills as self-reported, and why', async () => {
    setup(result([member()]))
    expect(await screen.findByText(/strong · 72\/100/)).toBeInTheDocument()
    expect(screen.getByText(/advanced, self-reported/)).toBeInTheDocument()
    expect(screen.getByText(/project needs they haven.t listed: Vue/i)).toBeInTheDocument()
    expect(screen.getByText(/could also fit: Full-Stack Developer \(55\)/i)).toBeInTheDocument()
    expect(screen.getByText('From saved profile')).toBeInTheDocument()
    expect(screen.getByText(/not assignments/i)).toBeInTheDocument()
  })

  it('labels a suggestion as advice until decided, and offers actions only on your own card', async () => {
    setup(result([member(), member({ user_id: 'u2', name: 'Ben' })]))
    expect(await screen.findAllByText(/Suggested/)).toHaveLength(2)
    expect(screen.getAllByRole('button', { name: 'Accept' })).toHaveLength(1)
    expect(screen.queryByText(/Confirmed as/)).not.toBeInTheDocument()
  })

  it('accepting records the decision and shows it as confirmed', async () => {
    const user = userEvent.setup()
    vi.mocked(api.setMyRoleDecision).mockResolvedValue({ data: [{ user_id: 'u1', name: 'Ada', status: 'accepted', role: 'Frontend Developer' }] })
    setup(result([member()]))
    await user.click(await screen.findByRole('button', { name: 'Accept' }))
    expect(api.setMyRoleDecision).toHaveBeenCalledWith('t1', { status: 'accepted', role: 'Frontend Developer' })
    expect(await screen.findByText('Confirmed as Frontend Developer')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Accept' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Undo my decision' })).toBeInTheDocument()
  })

  it('declining and choosing another role both go through the decision API', async () => {
    const user = userEvent.setup()
    vi.mocked(api.setMyRoleDecision).mockResolvedValue({ data: [] })
    setup(result([member()]))
    await user.click(await screen.findByRole('button', { name: 'Decline' }))
    expect(api.setMyRoleDecision).toHaveBeenLastCalledWith('t1', { status: 'rejected', role: 'Frontend Developer' })

    await user.click(screen.getByRole('button', { name: 'Choose a different role' }))
    await waitFor(() => expect(screen.getByRole('option', { name: 'QA / Test Engineer' })).toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Confirm role' })).toBeDisabled()
    await user.selectOptions(screen.getByLabelText('Choose your role'), 'QA / Test Engineer')
    await user.click(screen.getByRole('button', { name: 'Confirm role' }))
    expect(api.setMyRoleDecision).toHaveBeenLastCalledWith('t1', { status: 'custom', role: 'QA / Test Engineer' })
  })

  it('shows a failed decision without losing the suggestion', async () => {
    const user = userEvent.setup()
    vi.mocked(api.setMyRoleDecision).mockRejectedValue(new Error('No team found, or you are not a member.'))
    setup(result([member()]))
    await user.click(await screen.findByRole('button', { name: 'Accept' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/not a member/)
    expect(screen.getByRole('button', { name: 'Accept' })).toBeInTheDocument()
  })

  it('shows teammates decisions read-only', async () => {
    setup(result([member({ user_id: 'u2', name: 'Ben' })], [{ user_id: 'u2', name: 'Ben', status: 'custom', role: 'QA / Test Engineer' }]), 'u1')
    expect(await screen.findByText('Chose QA / Test Engineer instead')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Accept' })).not.toBeInTheDocument()
  })

  it('members with no skills get a message and a profile link, not a role', async () => {
    setup(result([member({ suggested: null, alternatives: [], source: 'none', profile_status: 'not_started', message: 'No skills on file yet - complete your profile.' })]))
    expect(await screen.findByText(/no skills on file yet/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Add your profile' })).toHaveAttribute('href', '/profile?setup=1')
    expect(screen.queryByRole('button', { name: 'Accept' })).not.toBeInTheDocument()
  })

  it('manual-only members are pointed to the profile', async () => {
    setup(result([member({ source: 'manual', profile_status: 'not_started' })]))
    expect(await screen.findByText(/only the skills you typed/i)).toBeInTheDocument()
    expect(screen.getByText('From skills entered for this team')).toBeInTheDocument()
  })

  it('shows team coverage as advice: covered, no owner, optional roles', async () => {
    setup(result([member()]))
    const coverage = await screen.findByLabelText('Team coverage')
    expect(coverage).toHaveTextContent('Covered · Frontend Developer: Ada')
    expect(coverage).toHaveTextContent('No owner · Backend Developer')
    expect(coverage).toHaveTextContent('Also useful if the team has capacity: DevOps Engineer')
  })

  it('shows the balanced-split suggestion only when it differs, and says nobody is auto-assigned', async () => {
    const res = result([member()])
    res.role_fit.team = { ...TEAM, plan: [{ ...TEAM.plan[0], role: 'Backend Developer', differs: true }] }
    setup(res)
    expect(await screen.findByText(/Ada: Backend Developer instead of Frontend Developer/)).toBeInTheDocument()
    expect(screen.getByText(/nobody is assigned automatically/i)).toBeInTheDocument()
  })

  it('renders nothing when the server sent no role_fit', () => {
    const { container } = setup({ decisions: [] })
    expect(container).toBeEmptyDOMElement()
  })
})

describe('RoleFitPanel sharing hints', () => {
  it('tells you on your own card when teammates cannot see your profile, with a link', async () => {
    setup(result([member({ profile_shared: false })]))
    expect(await screen.findByText(/teammates can.t see your profile skills/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Change sharing' })).toHaveAttribute('href', '/profile')
  })

  it('shows no hint when sharing is on, or on other people’s cards', async () => {
    setup(result([member({ profile_shared: true }), member({ user_id: 'u2', name: 'Ben' })]))
    await screen.findAllByText(/Suggested/)
    expect(screen.queryByText(/teammates can.t see your profile skills/i)).not.toBeInTheDocument()
  })

  it('shows the neutral unavailable message for a teammate without revealing why', async () => {
    const msg = 'No profile information is available for matching - it has not been shared with the team, or has not been added. That says nothing about what this person can do.'
    setup(result([member({ user_id: 'u2', name: 'Ben', suggested: null, alternatives: [], source: 'none', profile_status: 'not_started', info_unavailable: true, message: msg })]))
    expect(await screen.findByText(/no profile information is available for matching/i)).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /profile/i })).not.toBeInTheDocument()
  })
})
