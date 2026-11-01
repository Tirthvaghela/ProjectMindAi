import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import NotificationsBell from './NotificationsBell'
import api from '../services/api'

vi.mock('../services/api', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    default: Object.fromEntries(Object.keys(actual.default).map((key) => [key, vi.fn()])),
  }
})

const note = (over) => ({
  notification_id: 'n1', type: 'team_join', title: 'Sam joined Team', body: 'Sam joined your team.', team_id: 't1', project_id: 'pm-1',
  read: false, created_at: '2026-03-04T10:00:00+00:00', ...over,
})

function renderBell(items, unread = items.filter((n) => !n.read).length) {
  vi.mocked(api.notifications).mockResolvedValue({ data: items, unread })
  vi.mocked(api.markNotificationRead).mockResolvedValue({ data: { read: true } })
  return render(
    <MemoryRouter>
      <NotificationsBell />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.resetAllMocks()
})

describe('NotificationsBell', () => {
  it('renders the existing notification types unchanged', async () => {
    const user = userEvent.setup()
    renderBell([
      note({ notification_id: 'a', type: 'team_join' }),
      note({ notification_id: 'b', type: 'team_message', title: 'New message in Team', body: 'Sam: hi' }),
      note({ notification_id: 'c', type: 'team_leave', title: 'Sam left Team', body: 'Sam is no longer on your team.' }),
    ])
    await user.click(await screen.findByRole('button', { name: /Notifications, 3 unread/ }))
    expect(screen.getByText('Sam joined Team')).toBeInTheDocument()
    expect(screen.getByText('Sam: hi')).toBeInTheDocument()
    expect(screen.getByText('Sam left Team')).toBeInTheDocument()
  })

  it('renders every sub-team type and an unknown future type without crashing', async () => {
    const user = userEvent.setup()
    renderBell([
      note({ notification_id: 'a', type: 'subteam_added', title: 'You were added to Backend', body: 'You are now on the “Backend” sub-team of Team.' }),
      note({ notification_id: 'b', type: 'subteam_join', title: 'Sam joined Backend', body: 'Sam joined the “Backend” sub-team.' }),
      note({ notification_id: 'c', type: 'subteam_message', title: 'New message in Backend', body: 'Sam posted in the “Backend” sub-team chat.' }),
      note({ notification_id: 'd', type: 'subteam_task', title: 'New task in Backend', body: 'A task was assigned to you in the “Backend” sub-team.' }),
      note({ notification_id: 'e', type: 'something_from_the_future', title: 'Mystery', body: 'Unknown kind' }),
    ])
    await user.click(await screen.findByRole('button', { name: /Notifications, 5 unread/ }))
    for (const text of ['You were added to Backend', 'Sam joined Backend', 'New message in Backend', 'New task in Backend', 'Mystery']) {
      expect(screen.getByText(text)).toBeInTheDocument()
    }
  })

  it('tolerates missing optional fields and links to the parent team (never a sub-team secret)', async () => {
    const user = userEvent.setup()
    renderBell([
      note({ notification_id: 'a', type: 'subteam_task', title: 'New task in Backend', team_id: 't9' }),
      note({ notification_id: 'b', type: 'weird', title: undefined, body: undefined, team_id: null, project_id: undefined }),
    ])
    await user.click(await screen.findByRole('button', { name: /Notifications, 2 unread/ }))
    const links = screen.getAllByRole('link')
    expect(links[0]).toHaveAttribute('href', '/teams/t9')
    expect(links[1]).toHaveAttribute('href', '/teams')
  })

  it('shows the empty state and survives a failed poll', async () => {
    const user = userEvent.setup()
    renderBell([])
    await user.click(await screen.findByRole('button', { name: 'Notifications' }))
    expect(screen.getByText('Nothing yet')).toBeInTheDocument()
  })

  it('does not disturb the page when the notification request fails', async () => {
    vi.mocked(api.notifications).mockRejectedValue(new Error('down'))
    render(
      <MemoryRouter>
        <NotificationsBell />
      </MemoryRouter>,
    )
    expect(await screen.findByRole('button', { name: 'Notifications' })).toBeInTheDocument()
  })

  it('marks one notification read on click', async () => {
    const user = userEvent.setup()
    renderBell([note({ notification_id: 'a', type: 'subteam_message', title: 'New message in Backend', body: 'Sam posted.' })])
    await user.click(await screen.findByRole('button', { name: /Notifications, 1 unread/ }))
    await user.click(screen.getByText('New message in Backend'))
    expect(api.markNotificationRead).toHaveBeenCalledWith('a')
  })
})
