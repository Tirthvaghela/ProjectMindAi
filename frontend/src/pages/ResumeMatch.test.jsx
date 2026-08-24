import { describe, expect, it, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '../test/testUtils.jsx'
import ResumeMatch from './ResumeMatch'
import api from '../services/api'

vi.mock('../services/api', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    default: Object.fromEntries(Object.keys(actual.default).map((key) => [key, vi.fn()])),
  }
})

const MATCHED_PROJECT = {
  project_id: 'pm-001',
  title: 'Campus Ride Share Matcher',
  difficulty: 'Intermediate',
  domain: 'Web Development',
  duration_weeks: 8,
  description: 'Matches commuters travelling similar routes.',
  technologies: ['Python', 'Flask'],
  skills_you_have: ['Python'],
  skills_to_learn: ['Flask'],
}

beforeEach(() => {
  window.localStorage.clear()
  vi.mocked(api.listFavorites).mockResolvedValue({ data: [] })
})

describe('ResumeMatch — idle state', () => {
  it('shows the empty state before a résumé is submitted', () => {
    renderWithProviders(<ResumeMatch />)
    expect(screen.getByText('Add your résumé to get started')).toBeInTheDocument()
  })

  it('shows a validation error when submitting with neither a file nor text', async () => {
    const user = userEvent.setup()
    renderWithProviders(<ResumeMatch />)
    await user.click(screen.getByRole('button', { name: /find matching projects/i }))
    expect(await screen.findByText(/upload a résumé file.*or paste your résumé text/i)).toBeInTheDocument()
    expect(api.resumeSuggest).not.toHaveBeenCalled()
  })
})

describe('ResumeMatch — pasted text', () => {
  it('submits pasted résumé text and renders the matched project', async () => {
    vi.mocked(api.resumeSuggest).mockResolvedValue({
      detected_skills: ['Python', 'Flask'],
      query_used: 'Python, Flask',
      count: 1,
      data: [MATCHED_PROJECT],
    })

    const user = userEvent.setup()
    renderWithProviders(<ResumeMatch />)

    await user.type(screen.getByLabelText(/paste your résumé text/i), 'Experienced with Python and Flask.')
    await user.click(screen.getByRole('button', { name: /find matching projects/i }))

    expect(await screen.findByText('Campus Ride Share Matcher')).toBeInTheDocument()
    expect(screen.getByText('Skills we found on your résumé')).toBeInTheDocument()
    expect(api.resumeSuggest).toHaveBeenCalledWith(
      expect.objectContaining({ text: 'Experienced with Python and Flask.' }),
    )
  })

  it('shows a loading state while matching', async () => {
    let resolveSuggest
    vi.mocked(api.resumeSuggest).mockReturnValue(
      new Promise((resolve) => {
        resolveSuggest = resolve
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<ResumeMatch />)

    await user.type(screen.getByLabelText(/paste your résumé text/i), 'Python developer.')
    await user.click(screen.getByRole('button', { name: /find matching projects/i }))

    expect(await screen.findByText(/matching your résumé against the catalogue/i)).toBeInTheDocument()
    resolveSuggest({ detected_skills: [], count: 0, data: [] })
  })

  it('shows a no-strong-matches state for an empty result', async () => {
    vi.mocked(api.resumeSuggest).mockResolvedValue({ detected_skills: [], count: 0, data: [] })
    const user = userEvent.setup()
    renderWithProviders(<ResumeMatch />)

    await user.type(screen.getByLabelText(/paste your résumé text/i), 'A résumé with no catalogue overlap.')
    await user.click(screen.getByRole('button', { name: /find matching projects/i }))

    expect(await screen.findByText('No strong matches')).toBeInTheDocument()
  })
})

describe('ResumeMatch — file upload', () => {
  it('submits an uploaded file and renders results', async () => {
    vi.mocked(api.resumeSuggest).mockResolvedValue({
      detected_skills: ['Python'],
      count: 1,
      data: [MATCHED_PROJECT],
    })

    const user = userEvent.setup()
    renderWithProviders(<ResumeMatch />)

    const file = new File(['Python developer with Flask experience.'], 'resume.txt', { type: 'text/plain' })
    await user.upload(screen.getByLabelText(/résumé file/i), file)
    expect(screen.getByText('resume.txt')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /find matching projects/i }))

    expect(await screen.findByText('Campus Ride Share Matcher')).toBeInTheDocument()
    expect(api.resumeSuggest).toHaveBeenCalledWith(expect.objectContaining({ file }))
  })
})

describe('ResumeMatch — error state', () => {
  it('shows an error with a retry action when matching fails', async () => {
    vi.mocked(api.resumeSuggest).mockRejectedValue(new Error('Could not read that résumé.'))
    const user = userEvent.setup()
    renderWithProviders(<ResumeMatch />)

    await user.type(screen.getByLabelText(/paste your résumé text/i), 'Python developer.')
    await user.click(screen.getByRole('button', { name: /find matching projects/i }))

    // Shown in two places at once by design — the sidebar's own inline
    // error line and the main panel's ErrorNotice.
    expect((await screen.findAllByText('Could not read that résumé.')).length).toBeGreaterThan(0)

    vi.mocked(api.resumeSuggest).mockResolvedValue({ detected_skills: [], count: 1, data: [MATCHED_PROJECT] })
    await user.click(screen.getByRole('button', { name: /retry|try again/i }))
    expect(await screen.findByText('Campus Ride Share Matcher')).toBeInTheDocument()
  })
})
