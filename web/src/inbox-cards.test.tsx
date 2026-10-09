import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { Inbox, ago, openLabel, splitBody } from './notify/Inbox'
import { GENERAL_US, mockApi, renderAt } from './test-utils'

beforeEach(() => localStorage.clear())
afterEach(() => vi.unstubAllGlobals())

const item = (over: Record<string, unknown> = {}) => ({
  id: 1,
  source: 'signal',
  subject: 'equity',
  severity: 'high',
  title: 'equity is 12.0 pp over its target',
  body: 'Direct new money to bring it back.\nequity weighs 62% against 50%; the band is 5 pp.',
  link: '/strategies',
  created_at: new Date(Date.now() - 2 * 3600_000).toISOString(),
  read_at: null,
  deliveries: [],
  ...over,
})

const show = (items: unknown[], unread = 1) => {
  mockApi({
    '/api/v1/settings/general': GENERAL_US,
    '/api/v1/notifications': { items, total: items.length, unread },
    'POST /api/v1/notifications/read': { unread: 0 },
  })
  return renderAt(<Inbox />)
}

describe('an inbox item as a card', () => {
  it('leads with the title and what it is, then a one-line summary, with the rest as details', async () => {
    show([item()])
    const card = await screen.findByRole('listitem', { name: 'equity is 12.0 pp over its target' })
    expect(within(card).getByRole('heading', { level: 3 })).toHaveTextContent(
      'equity is 12.0 pp over its target',
    )
    expect(within(card).getByText('High')).toBeVisible() // how loud
    expect(within(card).getByText('Strategy')).toBeVisible() // where it comes from
    expect(within(card).getByText('equity')).toBeVisible() // what it is about
    expect(within(card).getByText('2 hours ago')).toBeVisible()
    expect(within(card).getByText('Direct new money to bring it back.')).toBeVisible()
    const more = within(card).getByText('equity weighs 62% against 50%; the band is 5 pp.')
    expect(more).not.toBeVisible() // in the details, which are closed
    await userEvent.click(within(card).getByText('Show details'))
    expect(more).toBeVisible()
  })

  it('has a main button that says where it goes, and a button to mark it read', async () => {
    const { calls } = (() => {
      const m = mockApi({
        '/api/v1/settings/general': GENERAL_US,
        '/api/v1/notifications': {
          items: [item({ link: '/holdings/4' })],
          total: 1,
          unread: 1,
        },
        'POST /api/v1/notifications/read': { unread: 0 },
      })
      return m
    })()
    renderAt(<Inbox />)
    const card = await screen.findByRole('listitem')
    expect(within(card).getByRole('link', { name: /^Open position/ })).toHaveAttribute(
      'href',
      '/holdings/4',
    )
    await userEvent.click(
      within(card).getByRole('button', {
        name: 'Mark as read: equity is 12.0 pp over its target',
      }),
    )
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({
      ids: [1],
      all: false,
      read: true,
    })
  })

  it('shows a read item calmly, with no mark-as-read button, and a short one without details', async () => {
    show(
      [
        item({
          read_at: '2026-10-05T09:00:00Z',
          body: 'Short and complete.',
          link: null,
        }),
      ],
      0,
    )
    const card = await screen.findByRole('listitem')
    expect(within(card).queryByRole('button', { name: /Mark as read/ })).toBeNull()
    expect(within(card).queryByRole('link')).toBeNull()
    expect(within(card).queryByText('Show details')).toBeNull()
    expect(within(card).getByText('Short and complete.')).toBeVisible()
  })

  it('switches between all, unread and read with a segmented control', async () => {
    const { calls } = mockApi({
      '/api/v1/settings/general': GENERAL_US,
      '/api/v1/notifications': { items: [], total: 0, unread: 0 },
    })
    renderAt(<Inbox />)
    const group = await screen.findByRole('group', { name: 'Read' })
    expect(within(group).getByRole('button', { name: 'All' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    await userEvent.click(within(group).getByRole('button', { name: 'Unread' }))
    expect(within(group).getByRole('button', { name: 'Unread' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    expect(calls.some((c) => c.path === '/api/v1/notifications')).toBe(true)
  })
})

describe('the helpers of an inbox card', () => {
  it('takes the first line as the summary and the rest as details', () => {
    expect(splitBody('One line.')).toEqual({ summary: 'One line.', details: '' })
    expect(splitBody('First.\nSecond.\nThird.')).toEqual({
      summary: 'First.',
      details: 'Second.\nThird.',
    })
  })

  it('cuts a very long first line at a word and keeps the whole text as details', () => {
    const long = `${'word '.repeat(60)}end`
    const { summary, details } = splitBody(long)
    expect(summary.length).toBeLessThanOrEqual(161)
    expect(summary.endsWith('…')).toBe(true)
    expect(details).toBe(long)
  })

  it('names the button by where the link leads', () => {
    const t = ((key: string) => key) as never
    expect(openLabel('/holdings/3', t)).toBe('inbox.openPosition')
    expect(openLabel('/news?cluster=2', t)).toBe('inbox.openStory')
    expect(openLabel('/strategies/review?quarter=2024Q1', t)).toBe('inbox.openReview')
    expect(openLabel('/insights?recommendation=5', t)).toBe('inbox.openAdvice')
    expect(openLabel('/strategies', t)).toBe('inbox.open')
  })

  it('writes the time as a distance from now', () => {
    const now = Date.parse('2026-10-09T12:00:00Z')
    expect(ago('2026-10-09T11:55:00Z', now)).toBe('5 minutes ago')
    expect(ago('2026-10-09T10:00:00Z', now)).toBe('2 hours ago')
    expect(ago('2026-10-08T12:00:00Z', now)).toBe('yesterday')
    expect(ago('2026-10-09T11:59:40Z', now)).toBe('now')
  })
})
