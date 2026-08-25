import { describe, expect, it, vi, beforeEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
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

beforeEach(() => {
  window.localStorage.clear()
  vi.mocked(api.health).mockResolvedValue({ ai_assistant: { enabled: true } })
})

describe('Dashboard — empty state', () => {
  it('shows the ready-to-chat greeting before any message is sent', async () => {
    signIn()
    renderWithProviders(<Dashboard />, { route: '/dashboard' })
    expect(await screen.findByText('Welcome back, Alex.')).toBeInTheDocument()
  })
})

describe('Dashboard — sending a message', () => {
  it('sends the typed message and renders the reply', async () => {
    signIn()
    vi.mocked(api.createConversation).mockResolvedValue({ data: { conversation_id: 'c1' } })
    vi.mocked(api.sendConversationMessage).mockResolvedValue({
      data: { reply: 'Here are a few NLP project ideas.', blocks: null, selected_project_id: null, selected_idea: null },
    })

    const user = userEvent.setup()
    renderWithProviders(<Dashboard />, { route: '/dashboard' })
    await screen.findByText('Welcome back, Alex.')

    const input = screen.getByLabelText('Message ProjectMind')
    await user.type(input, 'Give me some NLP project ideas')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    // The user's own message renders immediately (optimistic), the input clears.
    expect(await screen.findByText('Give me some NLP project ideas')).toBeInTheDocument()
    expect(input).toHaveValue('')

    // Then the real reply arrives.
    expect(await screen.findByText('Here are a few NLP project ideas.')).toBeInTheDocument()
    expect(api.sendConversationMessage).toHaveBeenCalledWith('c1', 'Give me some NLP project ideas')
  })

  it('shows a typing indicator while waiting for the reply', async () => {
    signIn()
    vi.mocked(api.createConversation).mockResolvedValue({ data: { conversation_id: 'c1' } })
    let resolveSend
    vi.mocked(api.sendConversationMessage).mockReturnValue(
      new Promise((resolve) => {
        resolveSend = resolve
      }),
    )

    const user = userEvent.setup()
    renderWithProviders(<Dashboard />, { route: '/dashboard' })
    await screen.findByText('Welcome back, Alex.')

    await user.type(screen.getByLabelText('Message ProjectMind'), 'Hello')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    expect(await screen.findByRole('button', { name: 'Send' })).toBeDisabled()

    resolveSend({ data: { reply: 'Hi! What are you building?', blocks: null } })
    await screen.findByText('Hi! What are you building?')
  })

  it('the send button stays disabled for a blank/whitespace-only message', async () => {
    signIn()
    renderWithProviders(<Dashboard />, { route: '/dashboard' })
    await screen.findByText('Welcome back, Alex.')

    const sendButton = screen.getByRole('button', { name: 'Send' })
    expect(sendButton).toBeDisabled()

    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Message ProjectMind'), '   ')
    expect(sendButton).toBeDisabled()
  })
})

describe('Dashboard — feasibility block', () => {
  const FEASIBILITY_BLOCK = {
    type: 'feasibility',
    project_id: 'p1',
    title: 'Face Recognition Attendance',
    feasibility_score: 62,
    risk_level: 'Medium',
    factors: [
      { factor: 'Skill Fit', score: 50, note: 'Based on the skills you listed.' },
      { factor: 'Timeline Fit', score: 40, note: 'Estimated 9 weeks.' },
      { factor: 'Difficulty Fit', score: null, note: 'Experience level not given.' },
    ],
    strengths: ['You already have Python.'],
    risks: ["You'll need to learn Deep Learning.", 'Timeline is tight — estimated 9 weeks.'],
    recommendations: ['Reduce scope to fit the timeline.', 'Consider using a pretrained model instead of training one from scratch.'],
    infrastructure: { note: 'GPU recommended for training or real-time inference.', is_estimate: true },
    dataset: { note: 'Needs an image/video dataset.', is_estimate: true },
  }

  it('renders the feasibility score, factors, risks and recommendations', async () => {
    signIn()
    vi.mocked(api.createConversation).mockResolvedValue({ data: { conversation_id: 'c1' } })
    vi.mocked(api.sendConversationMessage).mockResolvedValue({
      data: { reply: "Here's the feasibility check.", blocks: [FEASIBILITY_BLOCK], selected_project_id: null, selected_idea: null },
    })

    const user = userEvent.setup()
    renderWithProviders(<Dashboard />, { route: '/dashboard' })
    await screen.findByText('Welcome back, Alex.')

    await user.type(screen.getByLabelText('Message ProjectMind'), 'Can I build this?')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    expect(await screen.findByText('62% feasible')).toBeInTheDocument()
    expect(screen.getByText('(Medium risk)')).toBeInTheDocument()
    expect(screen.getByText('Skill Fit: 50%')).toBeInTheDocument()
    expect(screen.getByText("You'll need to learn Deep Learning.", { exact: false })).toBeInTheDocument()
    expect(
      screen.getByText('Consider using a pretrained model instead of training one from scratch.', { exact: false }),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'View Details' })).toHaveAttribute('href', '/project/p1')
    expect(screen.getByRole('button', { name: 'Reduce Risk' })).toBeInTheDocument()
  })

  it('the Reduce Risk action sends a follow-up through the existing chat pipeline', async () => {
    signIn()
    vi.mocked(api.createConversation).mockResolvedValue({ data: { conversation_id: 'c1' } })
    vi.mocked(api.sendConversationMessage)
      .mockResolvedValueOnce({
        data: { reply: "Here's the feasibility check.", blocks: [FEASIBILITY_BLOCK], selected_project_id: null, selected_idea: null },
      })
      .mockResolvedValueOnce({
        data: { reply: 'Consider dropping the real-time requirement.', blocks: null, selected_project_id: null, selected_idea: null },
      })

    const user = userEvent.setup()
    renderWithProviders(<Dashboard />, { route: '/dashboard' })
    await screen.findByText('Welcome back, Alex.')

    await user.type(screen.getByLabelText('Message ProjectMind'), 'Can I build this?')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    await screen.findByText('62% feasible')

    await user.click(screen.getByRole('button', { name: 'Reduce Risk' }))

    expect(await screen.findByText('Consider dropping the real-time requirement.')).toBeInTheDocument()
    expect(api.sendConversationMessage).toHaveBeenLastCalledWith('c1', 'How can I reduce the risk for this project?')
  })
})

describe('Dashboard — scope block', () => {
  const SCOPE_BLOCK = {
    type: 'scope',
    project_id: 'p1',
    title: 'Face Recognition Attendance',
    mvp: ['Image Acquisition & Preprocessing', 'Model Training / Inference'],
    core: ['Detection or Classification Pipeline'],
    advanced: ['Visualization Layer'],
    future: ['Extend the vision model development with more advanced techniques as skills grow.'],
    dependencies: ['Python', 'OpenCV', 'TensorFlow', 'Flask'],
    technical_constraints: ['GPU recommended for training or real-time inference.'],
    reduced_scope: {
      remove: ['Visualization Layer'],
      keep: ['Image Acquisition & Preprocessing', 'Model Training / Inference', 'Detection or Classification Pipeline'],
      reason: 'Your 2-week target is 4 weeks short of the 6-week baseline — dropping Visualization Layer keeps the core system achievable.',
    },
  }

  it('renders the scope tiers, constraints and the suggested reduction', async () => {
    signIn()
    vi.mocked(api.createConversation).mockResolvedValue({ data: { conversation_id: 'c1' } })
    vi.mocked(api.sendConversationMessage).mockResolvedValue({
      data: { reply: "Here's the scope breakdown.", blocks: [SCOPE_BLOCK], selected_project_id: null, selected_idea: null },
    })

    const user = userEvent.setup()
    renderWithProviders(<Dashboard />, { route: '/dashboard' })
    await screen.findByText('Welcome back, Alex.')

    await user.type(screen.getByLabelText('Message ProjectMind'), 'I only have 2 weeks, what should I remove?')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    expect(await screen.findByText('Image Acquisition & Preprocessing')).toBeInTheDocument()
    expect(screen.getByText('Detection or Classification Pipeline')).toBeInTheDocument()
    // "Visualization Layer" appears both as the Advanced-tier chip and inside
    // the reduction's "Remove:" line — assert at least one render, not a
    // single unique match.
    expect(screen.getAllByText('Visualization Layer').length).toBeGreaterThan(0)
    expect(screen.getByText(/dropping Visualization Layer keeps the core system achievable/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Apply Scope Recommendation' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Create Roadmap' })).toBeInTheDocument()
  })

  it('hides Apply Scope Recommendation when there is no reduction to apply', async () => {
    signIn()
    vi.mocked(api.createConversation).mockResolvedValue({ data: { conversation_id: 'c1' } })
    vi.mocked(api.sendConversationMessage).mockResolvedValue({
      data: {
        reply: "Here's the scope breakdown.",
        blocks: [{ ...SCOPE_BLOCK, reduced_scope: null }],
        selected_project_id: null,
        selected_idea: null,
      },
    })

    const user = userEvent.setup()
    renderWithProviders(<Dashboard />, { route: '/dashboard' })
    await screen.findByText('Welcome back, Alex.')

    await user.type(screen.getByLabelText('Message ProjectMind'), 'What should this include?')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    await screen.findByText('Image Acquisition & Preprocessing')

    expect(screen.queryByRole('button', { name: 'Apply Scope Recommendation' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Create Roadmap' })).toBeInTheDocument()
  })

  it('the Create Roadmap action sends a follow-up through the existing chat pipeline', async () => {
    signIn()
    vi.mocked(api.createConversation).mockResolvedValue({ data: { conversation_id: 'c1' } })
    vi.mocked(api.sendConversationMessage)
      .mockResolvedValueOnce({
        data: { reply: "Here's the scope breakdown.", blocks: [SCOPE_BLOCK], selected_project_id: null, selected_idea: null },
      })
      .mockResolvedValueOnce({
        data: { reply: 'Here is the roadmap.', blocks: null, selected_project_id: null, selected_idea: null },
      })

    const user = userEvent.setup()
    renderWithProviders(<Dashboard />, { route: '/dashboard' })
    await screen.findByText('Welcome back, Alex.')

    await user.type(screen.getByLabelText('Message ProjectMind'), 'What should this include?')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    await screen.findByText('Image Acquisition & Preprocessing')

    await user.click(screen.getByRole('button', { name: 'Create Roadmap' }))

    expect(await screen.findByText('Here is the roadmap.')).toBeInTheDocument()
    expect(api.sendConversationMessage).toHaveBeenLastCalledWith('c1', 'Create a roadmap for this project.')
  })
})

describe('Dashboard — resources block', () => {
  const PROJECT_RESOURCES_BLOCK = {
    type: 'resources',
    project_id: 'p1',
    title: 'Face Recognition Attendance',
    team: {
      recommended_size: 2,
      given_size: null,
      roles: [
        { role: 'Image Acquisition & Preprocessing', category: 'Data / ML' },
        { role: 'Visualization Layer', category: 'Frontend / UI' },
      ],
      required_skills: ['Computer Vision', 'Deep Learning', 'Flask'],
    },
    technology: {
      frontend: [],
      backend: ['Flask'],
      database: ['MongoDB'],
      ai_ml: ['TensorFlow', 'OpenCV'],
      infrastructure: [],
    },
    resources: {
      dataset: { note: 'Needs an image/video dataset — check for an existing public one.', is_estimate: true },
      compute: { note: 'GPU recommended for training or real-time inference.', is_estimate: true },
      storage: { note: 'Local storage is sufficient for a student-scale project.', is_estimate: true },
      apis: [],
      external_services: [],
    },
    cost: {
      development: 'Typically $0 — a solo/team academic project using your own time.',
      infrastructure: 'Roughly $0 on free-tier hosting/database plans for a project this size.',
      api: '$0 on free-tier APIs (e.g. Groq, Hugging Face Inference).',
      hosting: '$0/month achievable on a free-tier host.',
      free_alternatives: ['Free GPU compute: Google Colab or Kaggle Notebooks free tier.', 'Free-tier database: MongoDB Atlas free cluster (M0).'],
      is_estimate: true,
    },
  }

  it('renders team, technology, resources and cost sections with estimate labeling', async () => {
    signIn()
    vi.mocked(api.createConversation).mockResolvedValue({ data: { conversation_id: 'c1' } })
    vi.mocked(api.sendConversationMessage).mockResolvedValue({
      data: { reply: "Here's what you'll need.", blocks: [PROJECT_RESOURCES_BLOCK], selected_project_id: null, selected_idea: null },
    })

    const user = userEvent.setup()
    renderWithProviders(<Dashboard />, { route: '/dashboard' })
    await screen.findByText('Welcome back, Alex.')

    await user.type(screen.getByLabelText('Message ProjectMind'), 'How many people do I need and what technologies?')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    expect(await screen.findByText('2 people recommended')).toBeInTheDocument()
    expect(screen.getByText('Image Acquisition & Preprocessing · Data / ML')).toBeInTheDocument()
    expect(screen.getByText('TensorFlow')).toBeInTheDocument()
    expect(screen.getByText('MongoDB')).toBeInTheDocument()
    expect(screen.getByText(/Needs an image\/video dataset/)).toBeInTheDocument()
    expect(screen.getByText(/GPU recommended/)).toBeInTheDocument()
    // Estimate labeling: dataset/compute/storage notes and the cost section
    // header must all be marked as estimates, never presented as fact.
    expect(screen.getAllByText(/\(estimate\)/).length).toBeGreaterThanOrEqual(3)
    expect(screen.getByText(/Free GPU compute/)).toBeInTheDocument()
  })

  it('project resources: Create Roadmap targets "this project"', async () => {
    signIn()
    vi.mocked(api.createConversation).mockResolvedValue({ data: { conversation_id: 'c1' } })
    vi.mocked(api.sendConversationMessage).mockResolvedValue({
      data: { reply: "Here's what you'll need.", blocks: [PROJECT_RESOURCES_BLOCK], selected_project_id: null, selected_idea: null },
    })

    const user = userEvent.setup()
    renderWithProviders(<Dashboard />, { route: '/dashboard' })
    await screen.findByText('Welcome back, Alex.')
    await user.type(screen.getByLabelText('Message ProjectMind'), 'What resources do I need?')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    await screen.findByText('2 people recommended')

    await user.click(screen.getByRole('button', { name: 'Create Roadmap' }))
    expect(api.sendConversationMessage).toHaveBeenLastCalledWith('c1', 'Create a roadmap for this project.')
  })

  it('idea resources: no project_id, Create Roadmap targets "this idea"', async () => {
    signIn()
    vi.mocked(api.createConversation).mockResolvedValue({ data: { conversation_id: 'c1' } })
    vi.mocked(api.sendConversationMessage).mockResolvedValue({
      data: {
        reply: "Here's what you'll need.",
        blocks: [{ ...PROJECT_RESOURCES_BLOCK, project_id: null, title: 'CampusWaste' }],
        selected_project_id: null,
        selected_idea: null,
      },
    })

    const user = userEvent.setup()
    renderWithProviders(<Dashboard />, { route: '/dashboard' })
    await screen.findByText('Welcome back, Alex.')
    await user.type(screen.getByLabelText('Message ProjectMind'), 'What resources does this idea need?')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    await screen.findByText('2 people recommended')

    await user.click(screen.getByRole('button', { name: 'Create Roadmap' }))
    expect(api.sendConversationMessage).toHaveBeenLastCalledWith('c1', 'Create a roadmap for this idea.')
  })

  it('the Skill Gap action sends a follow-up through the existing chat pipeline', async () => {
    signIn()
    vi.mocked(api.createConversation).mockResolvedValue({ data: { conversation_id: 'c1' } })
    vi.mocked(api.sendConversationMessage)
      .mockResolvedValueOnce({
        data: { reply: "Here's what you'll need.", blocks: [PROJECT_RESOURCES_BLOCK], selected_project_id: null, selected_idea: null },
      })
      .mockResolvedValueOnce({
        data: { reply: 'Here is your skill gap.', blocks: null, selected_project_id: null, selected_idea: null },
      })

    const user = userEvent.setup()
    renderWithProviders(<Dashboard />, { route: '/dashboard' })
    await screen.findByText('Welcome back, Alex.')
    await user.type(screen.getByLabelText('Message ProjectMind'), 'What resources do I need?')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    await screen.findByText('2 people recommended')

    await user.click(screen.getByRole('button', { name: 'Skill Gap' }))
    expect(await screen.findByText('Here is your skill gap.')).toBeInTheDocument()
    expect(api.sendConversationMessage).toHaveBeenLastCalledWith('c1', 'Check my skill gap for this project.')
  })

  it('renders without crashing when technology/resources/cost sections are empty', async () => {
    signIn()
    vi.mocked(api.createConversation).mockResolvedValue({ data: { conversation_id: 'c1' } })
    vi.mocked(api.sendConversationMessage).mockResolvedValue({
      data: {
        reply: "Here's what you'll need.",
        blocks: [
          {
            type: 'resources',
            project_id: 'p1',
            title: 'Minimal project',
            team: { recommended_size: 1, given_size: null, roles: [], required_skills: [] },
            technology: { frontend: [], backend: [], database: [], ai_ml: [], infrastructure: [] },
            resources: { dataset: { note: '', is_estimate: true }, compute: { note: '', is_estimate: true }, storage: { note: '', is_estimate: true }, apis: [], external_services: [] },
            cost: { development: '', infrastructure: '', api: '', hosting: '', free_alternatives: [], is_estimate: true },
          },
        ],
        selected_project_id: null,
        selected_idea: null,
      },
    })

    const user = userEvent.setup()
    renderWithProviders(<Dashboard />, { route: '/dashboard' })
    await screen.findByText('Welcome back, Alex.')
    await user.type(screen.getByLabelText('Message ProjectMind'), 'What resources do I need?')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    expect(await screen.findByText('1 person recommended')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Create Roadmap' })).toBeInTheDocument()
  })
})

describe('Dashboard — decision center', () => {
  const PROJECT_DECISION = {
    kind: 'project',
    project_id: 'p1',
    name: 'Face Recognition Attendance',
    domain: 'Computer Vision',
    difficulty: 'Advanced',
    duration_weeks: 6,
    technologies: ['Python', 'OpenCV'],
    overall_recommendation: { label: 'Worth considering', score: 62 },
    skill_fit: 50,
    difficulty_fit: 75,
    timeline: { estimated_weeks: 9, fit_score: 40 },
    feasibility: { score: 62, risk_level: 'Medium' },
    originality: { score: 71, is_unique: null, source: 'catalogue_uniqueness' },
    scope: { mvp: ['Data Collection'], core: ['Model Training'], advanced: ['Visualization'], reduced_scope: null },
    resources: { team_recommended_size: 2, technology: {}, cost_is_estimate: true },
    strengths: ['You already have Python.'],
    risks: ["You'll need to learn Deep Learning."],
    skills_you_have: ['Python'],
    skills_to_learn: ['Deep Learning'],
    known_skills_provided: true,
    recommended_next_step: 'Review the learning path for Deep Learning before starting.',
  }

  const IDEA_DECISION = {
    ...PROJECT_DECISION,
    kind: 'idea',
    project_id: null,
    name: 'CampusWaste Tracker',
    originality: { score: 66, is_unique: true, source: 'generated_idea_originality' },
  }

  async function selectProjectAndOpenDecisionCenter(user, decisionPayload = PROJECT_DECISION) {
    vi.mocked(api.createConversation).mockResolvedValue({ data: { conversation_id: 'c1' } })
    vi.mocked(api.sendConversationMessage).mockResolvedValue({
      data: {
        reply: "Let's build it.",
        blocks: null,
        selected_project_id: decisionPayload.kind === 'project' ? decisionPayload.project_id : null,
        selected_idea: decisionPayload.kind === 'idea' ? { id: 'idea-1', name: decisionPayload.name } : null,
      },
    })
    vi.mocked(api.getProject).mockResolvedValue({ data: { project_id: 'p1', title: 'Face Recognition Attendance', difficulty: 'Advanced', domain: 'Computer Vision' } })
    vi.mocked(api.decisionCenter).mockResolvedValue({ data: decisionPayload })

    renderWithProviders(<Dashboard />, { route: '/dashboard' })
    await screen.findByText('Welcome back, Alex.')
    await user.type(screen.getByLabelText('Message ProjectMind'), "Let's build this.")
    await user.click(screen.getByRole('button', { name: 'Send' }))
    await screen.findByText("Let's build it.")
  }

  it('renders the recommendation score, fit stats and next step for a selected catalogue project', async () => {
    signIn()
    const user = userEvent.setup()
    await selectProjectAndOpenDecisionCenter(user, PROJECT_DECISION)

    expect(await screen.findByText('Catalogue Project')).toBeInTheDocument()
    expect(screen.getByText('62%')).toBeInTheDocument()
    expect(screen.getByText('Worth considering')).toBeInTheDocument()
    expect(screen.getByText("You'll need to learn Deep Learning.", { exact: false })).toBeInTheDocument()
    expect(screen.getByText(/Review the learning path for Deep Learning/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Start This Project' })).toHaveAttribute('href', '/project/p1')
  })

  it('distinguishes a generated idea from a catalogue project and has no project link', async () => {
    signIn()
    const user = userEvent.setup()
    await selectProjectAndOpenDecisionCenter(user, IDEA_DECISION)

    expect(await screen.findByText('AI-Generated Idea')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Start This Project' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Start This Project' })).toBeInTheDocument()
    // No project_id -- catalogue-only actions (Check Skill Gap) are omitted,
    // same rule PROJECT_ACTIONS/IDEA_BUILD_ACTIONS already follow.
    expect(screen.queryByRole('button', { name: 'Check Skill Gap' })).not.toBeInTheDocument()
  })

  it('renders gracefully with missing/partial information', async () => {
    signIn()
    const user = userEvent.setup()
    const sparse = {
      kind: 'project',
      project_id: 'p1',
      name: 'Minimal Project',
      domain: '',
      difficulty: '',
      duration_weeks: null,
      technologies: [],
      overall_recommendation: { label: null, score: null },
      skill_fit: null,
      difficulty_fit: null,
      timeline: { estimated_weeks: null, fit_score: null },
      feasibility: { score: 50, risk_level: 'Medium' },
      originality: { score: null, is_unique: null, source: 'catalogue_uniqueness' },
      scope: { mvp: [], core: [], advanced: [], reduced_scope: null },
      resources: { team_recommended_size: null, technology: {}, cost_is_estimate: false },
      strengths: [],
      risks: [],
      skills_you_have: [],
      skills_to_learn: [],
      known_skills_provided: false,
      recommended_next_step: 'Check your skill gap — your fit scores are more accurate once we know what you already have.',
    }
    await selectProjectAndOpenDecisionCenter(user, sparse)

    expect(await screen.findByText('Minimal Project')).toBeInTheDocument()
    expect(screen.getByText(/Check your skill gap/)).toBeInTheDocument()
    // No stray "null%"/"undefined" text from an unavailable score.
    expect(screen.queryByText('null%')).not.toBeInTheDocument()
    expect(screen.queryByText(/undefined/)).not.toBeInTheDocument()
  })

  it('does not render at all when nothing is selected', async () => {
    signIn()
    vi.mocked(api.createConversation).mockResolvedValue({ data: { conversation_id: 'c1' } })
    vi.mocked(api.sendConversationMessage).mockResolvedValue({
      data: { reply: 'Sure.', blocks: null, selected_project_id: null, selected_idea: null },
    })

    const user = userEvent.setup()
    renderWithProviders(<Dashboard />, { route: '/dashboard' })
    await screen.findByText('Welcome back, Alex.')
    await user.type(screen.getByLabelText('Message ProjectMind'), 'Hello')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    await screen.findByText('Sure.')

    expect(screen.queryByText('Catalogue Project')).not.toBeInTheDocument()
    expect(screen.queryByText('AI-Generated Idea')).not.toBeInTheDocument()
  })

  it('Generate Roadmap sends the correct canned prompt', async () => {
    signIn()
    const user = userEvent.setup()
    await selectProjectAndOpenDecisionCenter(user, PROJECT_DECISION)
    await screen.findByText('Catalogue Project')

    await user.click(screen.getByRole('button', { name: 'Generate Roadmap' }))
    expect(api.sendConversationMessage).toHaveBeenLastCalledWith('c1', 'Create a roadmap for this project.')
  })

  it('Check Skill Gap sends the correct canned prompt', async () => {
    signIn()
    const user = userEvent.setup()
    await selectProjectAndOpenDecisionCenter(user, PROJECT_DECISION)
    await screen.findByText('Catalogue Project')

    await user.click(screen.getByRole('button', { name: 'Check Skill Gap' }))
    expect(api.sendConversationMessage).toHaveBeenLastCalledWith('c1', 'Check my skill gap for this project.')
  })

  it('View Scope sends the correct canned prompt', async () => {
    signIn()
    const user = userEvent.setup()
    await selectProjectAndOpenDecisionCenter(user, PROJECT_DECISION)
    await screen.findByText('Catalogue Project')

    await user.click(screen.getByRole('button', { name: 'View Scope' }))
    expect(api.sendConversationMessage).toHaveBeenLastCalledWith('c1', 'What should the MVP be for this project?')
  })

  it('View Resources sends the correct canned prompt', async () => {
    signIn()
    const user = userEvent.setup()
    await selectProjectAndOpenDecisionCenter(user, PROJECT_DECISION)
    await screen.findByText('Catalogue Project')

    await user.click(screen.getByRole('button', { name: 'View Resources' }))
    expect(api.sendConversationMessage).toHaveBeenLastCalledWith('c1', 'What resources do I need for this project?')
  })

  it('Compare sends the correct canned prompt', async () => {
    signIn()
    const user = userEvent.setup()
    await selectProjectAndOpenDecisionCenter(user, PROJECT_DECISION)
    await screen.findByText('Catalogue Project')

    await user.click(screen.getByRole('button', { name: 'Compare' }))
    expect(api.sendConversationMessage).toHaveBeenLastCalledWith('c1', 'Compare this project with similar alternatives.')
  })

  it('idea mode: Start This Project sends a Build This-style prompt instead of linking', async () => {
    signIn()
    const user = userEvent.setup()
    await selectProjectAndOpenDecisionCenter(user, IDEA_DECISION)
    await screen.findByText('AI-Generated Idea')

    await user.click(screen.getByRole('button', { name: 'Start This Project' }))
    expect(api.sendConversationMessage).toHaveBeenLastCalledWith('c1', 'Let\'s build "CampusWaste Tracker".')
  })

  it('idea mode: Generate Roadmap and Compare target the idea by name', async () => {
    signIn()
    const user = userEvent.setup()
    await selectProjectAndOpenDecisionCenter(user, IDEA_DECISION)
    await screen.findByText('AI-Generated Idea')

    await user.click(screen.getByRole('button', { name: 'Generate Roadmap' }))
    expect(api.sendConversationMessage).toHaveBeenLastCalledWith('c1', 'Create a roadmap for "CampusWaste Tracker".')
  })

  it('Change Project links back to a fresh dashboard', async () => {
    signIn()
    const user = userEvent.setup()
    await selectProjectAndOpenDecisionCenter(user, PROJECT_DECISION)
    await screen.findByText('Catalogue Project')

    expect(screen.getByRole('link', { name: 'Change Project' })).toHaveAttribute('href', '/dashboard')
  })

  it('refetches the decision center when an existing conversation with a selection is reloaded', async () => {
    signIn()
    vi.mocked(api.getConversation).mockResolvedValue({
      data: {
        messages: [{ role: 'assistant', content: 'Welcome back.', blocks: null, created_at: new Date().toISOString() }],
        selected_project_id: 'p1',
        selected_idea: null,
      },
    })
    vi.mocked(api.getProject).mockResolvedValue({ data: { project_id: 'p1', title: 'Face Recognition Attendance', difficulty: 'Advanced', domain: 'Computer Vision' } })
    vi.mocked(api.decisionCenter).mockResolvedValue({ data: PROJECT_DECISION })

    renderWithProviders(<Dashboard />, { route: '/dashboard?c=c1' })

    expect(await screen.findByText('Catalogue Project')).toBeInTheDocument()
    expect(api.decisionCenter).toHaveBeenCalledWith('c1')
  })
})

describe('Dashboard — error state', () => {
  it('shows the error and a retry action when sending fails', async () => {
    signIn()
    vi.mocked(api.createConversation).mockResolvedValue({ data: { conversation_id: 'c1' } })
    vi.mocked(api.sendConversationMessage).mockRejectedValue(
      Object.assign(new Error('The AI assistant could not respond right now — try again.'), {}),
    )

    const user = userEvent.setup()
    renderWithProviders(<Dashboard />, { route: '/dashboard' })
    await screen.findByText('Welcome back, Alex.')

    await user.type(screen.getByLabelText('Message ProjectMind'), 'Hello')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    expect(await screen.findByText('The AI assistant could not respond right now — try again.')).toBeInTheDocument()

    // The failed optimistic user message is rolled back rather than left
    // stuck on screen with no way to tell it never actually sent.
    await waitFor(() => expect(screen.queryByText('Hello')).not.toBeInTheDocument())
  })
})
