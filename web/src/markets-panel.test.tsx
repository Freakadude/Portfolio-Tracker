import { screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MarketsPanel } from './system/MarketsPanel'
import { GENERAL_US, mockApi, renderAt } from './test-utils'

afterEach(() => vi.unstubAllGlobals())

const market = (over: Record<string, unknown> = {}) => ({
  mic: 'XETR',
  name: 'Xetra',
  timezone: 'Europe/Berlin',
  open_now: true,
  opens: '2026-10-06T07:00:00Z',
  closes: '2026-10-06T15:30:00Z',
  next_open: '2026-10-07T07:00:00Z',
  holdings: ['iShares Core S&P 500'],
  watching: [],
  ...over,
})

describe('market hours on the System page', () => {
  it('shows the hours in the owner time zone, whatever the exchange time zone is', async () => {
    mockApi({
      '/api/v1/settings/general': { ...GENERAL_US, timezone: 'Europe/Amsterdam' },
      '/api/v1/system/markets': [
        market(),
        market({
          mic: 'XNYS',
          name: 'NYSE',
          timezone: 'America/New_York',
          open_now: false,
          opens: '2026-10-06T13:30:00Z',
          closes: '2026-10-06T20:00:00Z',
          next_open: '2026-10-07T13:30:00Z',
          holdings: [],
          watching: ['Apple'],
        }),
      ],
    })
    renderAt(<MarketsPanel />)
    const xetra = (await screen.findByText('Xetra')).closest('tr') as HTMLElement
    // Xetra trades 09:00 to 17:30 in Frankfurt, which is the same clock in Amsterdam
    expect(within(xetra).getByText('09:00 – 17:30')).toBeInTheDocument()
    expect(within(xetra).getByText('Open')).toBeInTheDocument()
    expect(within(xetra).getByText('closes 17:30')).toBeInTheDocument()
    const nyse = screen.getByText('NYSE').closest('tr') as HTMLElement
    expect(within(nyse).getByText('15:30 – 22:00')).toBeInTheDocument() // 09:30 to 16:00 in New York
    expect(within(nyse).getByText('Closed')).toBeInTheDocument()
    expect(within(nyse).getByText('opens Wed 15:30')).toBeInTheDocument()
    expect(within(nyse).getByText('Watching: Apple')).toBeInTheDocument()
  })

  it('says a market is closed today on a weekend or holiday, and handles having none', async () => {
    mockApi({
      '/api/v1/settings/general': GENERAL_US,
      '/api/v1/system/markets': [market({ open_now: false, opens: null, closes: null })],
    })
    const first = renderAt(<MarketsPanel />)
    expect(await screen.findByText(/closed today/)).toBeInTheDocument()
    first.unmount()
    mockApi({ '/api/v1/settings/general': GENERAL_US, '/api/v1/system/markets': [] })
    renderAt(<MarketsPanel />)
    expect(await screen.findByText(/Nothing you hold or watch trades/)).toBeInTheDocument()
  })
})
