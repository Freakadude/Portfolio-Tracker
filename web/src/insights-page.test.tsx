import { screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { Insights } from './pages/Insights'
import { GENERAL_US, mockApi, renderAt } from './test-utils'

beforeEach(() => localStorage.clear())
afterEach(() => vi.unstubAllGlobals())

const routes = {
  '/api/v1/settings/general': GENERAL_US,
  '/api/v1/recommendations': [],
  '/api/v1/agent/usage': {
    enabled: true,
    key_set: true,
    paused: false,
    spent_eur: '0',
    budget_eur: '5',
  },
  '/api/v1/notifications': { items: [], total: 0, unread: 0 },
  '/api/v1/corporate-actions': [],
  '/api/v1/transactions': { items: [], total: 0 },
  '/api/v1/agent/track-record': {
    total: 0,
    actions: [],
    decisions: [],
    decision_horizon: 30,
    note: '',
  },
}

describe('the Insights page', () => {
  it('is a set of sections with clear headers, what needs a decision first', async () => {
    mockApi(routes)
    renderAt(<Insights />)
    await screen.findByText('No splits are waiting for you.')
    const headings = screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent ?? '')
    const order = ['Recommendations', 'Inbox', 'stock splits', 'dividends', 'Track record'].map(
      (name) => headings.findIndex((h) => h.includes(name)),
    )
    expect(order.every((i) => i >= 0)).toBe(true)
    expect([...order].sort((a, b) => a - b)).toEqual(order) // in this order
  })

  it('no longer has the question box; the chat panel and the position page have it', async () => {
    mockApi(routes)
    renderAt(<Insights />)
    await screen.findByText('No splits are waiting for you.')
    expect(screen.queryByText('Ask the portfolio')).toBeNull()
    expect(screen.queryByLabelText('Your question')).toBeNull()
  })

  it('closes a section from its header and shows what is waiting while it is closed', async () => {
    mockApi(routes)
    renderAt(<Insights />)
    await screen.findByText('No splits are waiting for you.')
    const splits = screen.getByRole('region', { name: /stock splits/ })
    // nothing waiting: it starts closed, and its header still says so
    expect(within(splits).getByRole('button', { name: /stock splits/ })).toHaveAttribute(
      'aria-expanded',
      'false',
    )
    expect(within(splits).getByText('No splits are waiting for you.')).toBeVisible()
  })
})
