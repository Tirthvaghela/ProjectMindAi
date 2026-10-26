import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import useCatalogueSize, { resetCatalogueSize } from './useCatalogueSize'
import { renderWithProviders } from '../test/testUtils.jsx'
import Account from '../pages/Account'
import api from '../services/api'

vi.mock('../services/api', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    default: Object.fromEntries(Object.keys(actual.default).map((key) => [key, vi.fn()])),
  }
})

function Size({ id = 'size' }) {
  const size = useCatalogueSize()
  return <span data-testid={id}>{size === null ? 'unknown' : String(size)}</span>
}

beforeEach(() => {
  vi.resetAllMocks()
  window.localStorage.clear()
  resetCatalogueSize()
  vi.mocked(api.health).mockResolvedValue({ status: 'ok' })
})

describe('useCatalogueSize', () => {
  it('reports the total the API returns, not a hard-coded figure', async () => {
    vi.mocked(api.listProjects).mockResolvedValue({ data: [], total: 1234 })
    render(<Size />)
    expect(screen.getByTestId('size')).toHaveTextContent('unknown')
    await waitFor(() => expect(screen.getByTestId('size')).toHaveTextContent('1234'))
    expect(api.listProjects).toHaveBeenCalledWith({ limit: 1 })
  })

  it('makes one request however many components ask at once', async () => {
    vi.mocked(api.listProjects).mockResolvedValue({ total: 868 })
    render(
      <>
        <Size id="a" />
        <Size id="b" />
      </>,
    )
    await waitFor(() => expect(screen.getByTestId('a')).toHaveTextContent('868'))
    expect(screen.getByTestId('b')).toHaveTextContent('868')
    expect(api.listProjects).toHaveBeenCalledTimes(1)
  })

  it.each([
    ['a failed request', () => vi.mocked(api.listProjects).mockRejectedValue(new Error('down'))],
    ['a response with no total', () => vi.mocked(api.listProjects).mockResolvedValue({ data: [] })],
    ['a non-numeric total', () => vi.mocked(api.listProjects).mockResolvedValue({ total: 'many' })],
    ['an unmocked/empty client', () => vi.mocked(api.listProjects).mockReturnValue(undefined)],
  ])('stays unknown (never a guess) after %s', async (_label, arrange) => {
    arrange()
    render(<Size />)
    await waitFor(() => expect(api.listProjects).toHaveBeenCalled())
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(screen.getByTestId('size')).toHaveTextContent('unknown')
  })
})

describe('Account — the "Projects indexed" figure', () => {
  it('shows the live catalogue size', async () => {
    vi.mocked(api.listProjects).mockResolvedValue({ total: 4321 })
    renderWithProviders(<Account />)
    expect(await screen.findByText('4,321')).toBeInTheDocument()
    expect(screen.queryByText(/850\+|500\+/)).not.toBeInTheDocument()
  })

  it('shows a dash rather than an invented number when the count is unavailable', async () => {
    vi.mocked(api.listProjects).mockRejectedValue(new Error('down'))
    renderWithProviders(<Account />)
    await waitFor(() => expect(api.listProjects).toHaveBeenCalled())
    expect(screen.getByText('Projects indexed')).toBeInTheDocument()
    expect(screen.queryByText(/\d,?\d{3}|850\+|500\+/)).not.toBeInTheDocument()
  })
})
