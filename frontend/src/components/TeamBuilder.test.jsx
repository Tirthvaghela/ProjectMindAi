import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '../test/testUtils.jsx'
import TeamBuilder, { UnassignedMembers } from './TeamBuilder'

const RESULT = {
  roles: ['Model Training', 'Frontend UI', 'Inference API'],
  assignments: [
    {
      member: 'Asha',
      assigned_role: 'Model Training',
      category: 'Data / ML',
      matched_skills: ['Python'],
      fallback: false,
      strongest_category: null,
    },
  ],
  unassigned_members: [
    {
      member: 'Bala',
      reason: 'no_skills',
      message: 'No skills recorded yet — add skills to get a role suggestion.',
      strongest_category: null,
      skills: [],
    },
  ],
  unfilled_roles: ['Frontend UI', 'Inference API'],
}

async function runBuild(onBuild) {
  renderWithProviders(<TeamBuilder onBuild={onBuild} />)
  const user = userEvent.setup()
  const [nameInput] = screen.getAllByRole('textbox')
  await user.type(nameInput, 'Asha')
  await user.click(screen.getByRole('button', { name: /suggest roles/i }))
}

describe('TeamBuilder — suggested roles rendering', () => {
  it('renders the returned assignment, the unassigned reason and the open roles — never a fallback claim', async () => {
    await runBuild(vi.fn().mockResolvedValue({ data: RESULT }))

    expect(await screen.findByText('Model Training')).toBeInTheDocument()
    expect(screen.getByText(/Bala — no role suggested/)).toBeInTheDocument()
    expect(screen.getByText(/No skills recorded yet/)).toBeInTheDocument()
    expect(screen.getByText(/Frontend UI, Inference API/)).toBeInTheDocument()
    expect(screen.queryByText(/keep every seat covered/i)).not.toBeInTheDocument()
  })

  it('shows the backend error message when the request fails', async () => {
    await runBuild(vi.fn().mockRejectedValue(new Error('Sign in required.')))
    expect(await screen.findByText('Sign in required.')).toBeInTheDocument()
  })

  it('renders an empty result without crashing or showing any assignment', async () => {
    await runBuild(
      vi.fn().mockResolvedValue({ data: { roles: [], assignments: [], unassigned_members: [], unfilled_roles: [] } }),
    )
    expect(screen.queryByText(/no role suggested/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/keep every seat covered/i)).not.toBeInTheDocument()
  })
})

describe('UnassignedMembers', () => {
  it('renders nothing for a missing or empty list (older responses have no such field)', () => {
    const { container } = renderWithProviders(<UnassignedMembers members={undefined} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('names the strongest area when one is known', () => {
    renderWithProviders(
      <UnassignedMembers
        members={[{ member: 'Devi', message: 'This project has no role in their strongest area.', strongest_category: 'Testing / QA' }]}
      />,
    )
    expect(screen.getByText(/Strongest area: Testing \/ QA/)).toBeInTheDocument()
  })
})
