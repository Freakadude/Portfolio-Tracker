import { screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { NewsTab } from './news/NewsTab'
import { mockApi, renderAt } from './test-utils'

afterEach(() => vi.unstubAllGlobals())

const source = (over: Record<string, unknown>) => ({
  id: 1,
  name: 'Source',
  kind: 'rss',
  url: 'https://example.org/feed.xml',
  language: 'en',
  trust_weight: '1',
  poll_minutes: 60,
  enabled: true,
  macro_series: [],
  items: 0,
  last_fetch_at: null,
  next_fetch_at: null,
  failures: 0,
  last_error: null,
  ...over,
})

const SOURCES = [
  source({ id: 1, name: 'Federal Reserve speeches and testimony' }),
  source({ id: 2, name: 'SEC filings for your holdings', kind: 'sec', url: '' }),
  source({
    id: 3,
    name: 'Nasdaq.com headlines for your shares',
    url: 'https://www.nasdaq.com/feed/rssoutbound?symbol={symbol}',
    trust_weight: '0.5',
  }),
]

const rowOf = async (table: HTMLElement, name: string) =>
  (await within(table).findByText(name)).closest('tr') as HTMLElement

describe('the ready-made sources of ADR 0062', () => {
  it('names the SEC and per-share sources and says they wait for the contact email', async () => {
    mockApi({
      '/api/v1/news/sources': SOURCES,
      '/api/v1/settings/news': { triage: true, sec_contact_email: '' },
    })
    renderAt(<NewsTab />)
    const table = await screen.findByRole('table', { name: 'News sources' })
    const sec = await rowOf(table, 'SEC filings for your holdings')
    expect(within(sec).getByText('SEC filings')).toBeInTheDocument()
    expect(await within(sec).findByText('Needs your contact email')).toBeInTheDocument()
    const perShare = await rowOf(table, 'Nasdaq.com headlines for your shares')
    expect(within(perShare).getByText('Feed per share')).toBeInTheDocument()
    expect(within(perShare).getByText('Needs your contact email')).toBeInTheDocument()
    const fed = await rowOf(table, 'Federal Reserve speeches and testimony')
    expect(within(fed).getByText('Working')).toBeInTheDocument() // a plain feed does not wait
    expect(screen.getByLabelText(/Your email for SEC filings/)).toBeInTheDocument()
  })

  it('shows them working once the email is set', async () => {
    mockApi({
      '/api/v1/news/sources': SOURCES,
      '/api/v1/settings/news': { triage: true, sec_contact_email: 'me@example.com' },
    })
    renderAt(<NewsTab />)
    const table = await screen.findByRole('table', { name: 'News sources' })
    await screen.findByDisplayValue('me@example.com')
    expect(within(table).queryByText('Needs your contact email')).toBeNull()
    expect(
      within(await rowOf(table, 'SEC filings for your holdings')).getByText('Working'),
    ).toBeVisible()
  })
})
