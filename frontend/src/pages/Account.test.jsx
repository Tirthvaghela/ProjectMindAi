import { describe, expect, it, vi, beforeEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '../test/testUtils.jsx'
import Account from './Account'
import api from '../services/api'

vi.mock('../services/api', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    default: Object.fromEntries(Object.keys(actual.default).map((key) => [key, vi.fn()])),
  }
})

beforeEach(() => {
  window.localStorage.clear()
  vi.mocked(api.health).mockResolvedValue({ status: 'ok' })
})

describe('Account — signed out', () => {
  it('defaults to the sign-in form', () => {
    renderWithProviders(<Account />)
    expect(screen.getByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(screen.queryByLabelText('Name')).not.toBeInTheDocument()
  })

  it('switches to the create-account form and back', async () => {
    const user = userEvent.setup()
    renderWithProviders(<Account />)

    await user.click(screen.getByText(/don.t have an account\? create one/i))
    expect(screen.getByRole('heading', { name: 'Create account' })).toBeInTheDocument()
    expect(screen.getByLabelText('Name')).toBeInTheDocument()

    await user.click(screen.getByText(/already have an account\? sign in/i))
    expect(screen.getByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
  })

  it('logs in successfully and shows the signed-in state', async () => {
    vi.mocked(api.login).mockResolvedValue({
      token: 'tok-123',
      data: { user_id: 'u1', name: 'Alex', email: 'alex@example.com' },
    })
    const user = userEvent.setup()
    renderWithProviders(<Account />)

    await user.type(screen.getByLabelText('Email'), 'alex@example.com')
    await user.type(screen.getByLabelText('Password'), 'correcthorse1')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))

    await waitFor(() => expect(api.login).toHaveBeenCalledWith('alex@example.com', 'correcthorse1'))
  })

  it('shows a clear error message when login fails', async () => {
    vi.mocked(api.login).mockRejectedValue(new Error('Invalid email or password.'))
    const user = userEvent.setup()
    renderWithProviders(<Account />)

    await user.type(screen.getByLabelText('Email'), 'alex@example.com')
    await user.type(screen.getByLabelText('Password'), 'wrongpassword')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByText('Invalid email or password.')).toBeInTheDocument()
  })

  it('signs up successfully with name, email, and password', async () => {
    vi.mocked(api.signup).mockResolvedValue({
      token: 'tok-456',
      data: { user_id: 'u2', name: 'Sam', email: 'sam@example.com' },
    })
    const user = userEvent.setup()
    renderWithProviders(<Account />)

    await user.click(screen.getByText(/don.t have an account\? create one/i))
    await user.type(screen.getByLabelText('Name'), 'Sam')
    await user.type(screen.getByLabelText('Email'), 'sam@example.com')
    await user.type(screen.getByLabelText('Password'), 'correcthorse1')
    await user.click(screen.getByRole('button', { name: 'Create account' }))

    await waitFor(() =>
      expect(api.signup).toHaveBeenCalledWith('sam@example.com', 'correcthorse1', 'Sam'),
    )
  })

  it('disables the submit button while the request is in flight', async () => {
    let resolveLogin
    vi.mocked(api.login).mockReturnValue(
      new Promise((resolve) => {
        resolveLogin = resolve
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<Account />)

    await user.type(screen.getByLabelText('Email'), 'alex@example.com')
    await user.type(screen.getByLabelText('Password'), 'correcthorse1')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByRole('button', { name: /one moment/i })).toBeDisabled()
    resolveLogin({ token: 't', data: { user_id: 'u1', name: 'Alex', email: 'a@example.com' } })
  })
})

describe('Account — signed in', () => {
  it('shows the account name/email instead of the form', async () => {
    window.localStorage.setItem('projectmind.authToken', 'tok-1')
    vi.mocked(api.me).mockResolvedValue({ data: { user_id: 'u1', name: 'Alex', email: 'alex@example.com' } })

    renderWithProviders(<Account />)

    expect(await screen.findByRole('heading', { name: 'Signed in' })).toBeInTheDocument()
    expect(screen.getByText('Alex')).toBeInTheDocument()
    expect(screen.getByText('alex@example.com')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Sign in' })).not.toBeInTheDocument()
  })
})
