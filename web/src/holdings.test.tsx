import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { Holdings } from './pages/Holdings'
import { GENERAL_US, mockApi, problem, renderAt } from './test-utils'

const position = (over: Record<string, unknown> = {}) => ({
  account_id: 1,
  account_name: 'Degiro',
  instrument_id: 1,
  isin: 'IE00B5BMR087',
  name: 'iShares Core S&P 500',
  ticker: 'SXR8',
  currency: 'EUR',
  asset_class: 'ETF',
  quantity: '5',
  avg_cost_eur: '120.1',
  cost_basis_eur: '600.5',
  market_value_eur: '700',
  unrealized_pnl_eur: '99.5',
  unrealized_ratio: '0.1657',
  realized_pnl_eur: '346.5',
  income_eur: '0',
  total_return_eur: '446',
  total_return_ratio: '0.2025',
  day_change_eur: '10',
  day_change_ratio: '0.0145',
  weight: '0.5932',
  market_value_native: '700',
  cost_basis_native: '600',
  unrealized_pnl_native: '100',
  first_trade_date: '2024-01-02',
  price: {
    date: '2024-04-10',
    close: '140',
    previous_close: '138',
    source: 'yahoo',
    overridden: false,
    stale: false,
  },
  note: null,
  ...over,
})

const loss = position({
  instrument_id: 2,
  name: 'Demo Emerging Markets',
  ticker: 'EMIM',
  isin: null,
  quantity: '10',
  avg_cost_eur: '30',
  cost_basis_eur: '300',
  market_value_eur: '280',
  unrealized_pnl_eur: '-20',
  unrealized_ratio: '-0.0667',
  day_change_eur: '-3',
  day_change_ratio: '-0.0106',
  weight: '0.2373',
  price: {
    date: '2024-03-01',
    close: '28',
    previous_close: '28.3',
    source: 'yahoo',
    overridden: false,
    stale: true,
  },
})
const unpriced = position({
  instrument_id: 3,
  name: 'Private bond',
  ticker: 'PRIVATE',
  isin: null,
  quantity: '1',
  avg_cost_eur: '100',
  cost_basis_eur: '100',
  market_value_eur: null,
  unrealized_pnl_eur: null,
  unrealized_ratio: null,
  day_change_eur: null,
  day_change_ratio: null,
  weight: null,
  price: null,
  note: 'No price yet.',
})

const totals = {
  positions: 3,
  unvalued_positions: 1,
  market_value_eur: '980',
  cost_basis_eur: '1000.5',
  unrealized_pnl_eur: '79.5',
  unrealized_ratio: '0.0883',
  realized_pnl_eur: '346.5',
  income_eur: '12.4',
  day_change_eur: null,
}

const accounts = [
  {
    id: 1,
    name: 'Degiro',
    broker: null,
    cost_basis_method: 'FIFO',
    base_currency: 'EUR',
    active: true,
    transaction_count: 3,
  },
]

beforeEach(() => {
  vi.stubGlobal(
    'confirm',
    vi.fn(() => true),
  )
})
afterEach(() => vi.unstubAllGlobals())

function api(extra: Record<string, unknown> = {}, rows = [position(), loss, unpriced]) {
  return mockApi({
    '/api/v1/settings/general': GENERAL_US,
    '/api/v1/accounts': accounts,
    '/api/v1/positions': { positions: rows, totals },
    '/api/v1/instruments': [],
    ...extra,
  })
}

describe('the positions table', () => {
  it('labels a newer intraday quote as delayed, with its time (FR-MD-05)', async () => {
    const quoted = position({
      price: {
        date: '2024-04-10',
        close: '140',
        previous_close: '138',
        source: 'yahoo',
        overridden: false,
        stale: false,
        delayed_price: '141.5',
        delayed_at: '2024-04-11T14:32:00+00:00',
      },
    })
    api({}, [quoted])
    renderAt(<Holdings />)
    const row = (await screen.findByText('iShares Core S&P 500')).closest('tr') as HTMLElement
    expect(within(row).getByText('Delayed 14:32')).toBeInTheDocument()
    expect(row).toHaveTextContent('141.5 EUR')
  })

  it('shows each position with figures in the chosen number format', async () => {
    api()
    renderAt(<Holdings />)
    const table = await screen.findByRole('table', { name: /positions with market value/i })
    expect(within(table).getByRole('link', { name: 'iShares Core S&P 500' })).toHaveAttribute(
      'href',
      '/holdings/1',
    )
    const row = within(table).getByRole('link', { name: 'iShares Core S&P 500' }).closest('tr')!
    expect(row).toHaveTextContent('SXR8 · IE00B5BMR087')
    expect(row).toHaveTextContent('€600.50') // cost basis
    expect(row).toHaveTextContent('€700.00') // market value
    expect(row).toHaveTextContent('59.3%') // weight
  })

  it('marks gains and losses with a sign and an arrow, not colour alone', async () => {
    api()
    renderAt(<Holdings />)
    const table = await screen.findByRole('table')
    const gain = within(table).getByRole('link', { name: 'iShares Core S&P 500' }).closest('tr')!
    expect(gain).toHaveTextContent('+€99.50 ▲')
    expect(gain).toHaveTextContent('+16.57% ▲')
    expect(within(gain).getAllByText('gain').length).toBeGreaterThan(0) // announced to screen readers
    const lossRow = within(table)
      .getByRole('link', { name: 'Demo Emerging Markets' })
      .closest('tr')!
    expect(lossRow).toHaveTextContent('−€20.00 ▼')
    expect(within(lossRow).getAllByText('loss').length).toBeGreaterThan(0)
  })

  it('flags a stale price, shows the as-of date on hover, and a missing price', async () => {
    api()
    renderAt(<Holdings />)
    const table = await screen.findByRole('table')
    const stale = within(table).getByRole('link', { name: 'Demo Emerging Markets' }).closest('tr')!
    expect(within(stale).getByText('Stale')).toHaveAttribute(
      'title',
      expect.stringContaining('3 trading days'),
    )
    expect(stale.querySelector('[title="Close of 2024-03-01 (yahoo)"]')).not.toBeNull()
    const none = within(table).getByRole('link', { name: 'Private bond' }).closest('tr')!
    expect(within(none).getByText('No price')).toHaveAttribute('title', 'No price yet.')
    expect(none).not.toHaveTextContent('Stale')
  })

  it('warns that unpriced positions are left out of the totals, and shows the totals row', async () => {
    api()
    renderAt(<Holdings />)
    expect(await screen.findByRole('alert')).toHaveTextContent('1 position has no price')
    const totalsRow = screen.getByRole('rowheader', { name: 'Total' }).closest('tr')!
    expect(totalsRow).toHaveTextContent('€980.00')
    expect(totalsRow).toHaveTextContent('€1,000.50')
    expect(screen.getByText(/Realized: €346\.50 · Income: €12\.40/)).toBeInTheDocument()
  })

  it('sorts when a column header is clicked and says so to assistive technology', async () => {
    api()
    renderAt(<Holdings />)
    const table = await screen.findByRole('table')
    const names = () =>
      within(table)
        .getAllByRole('link')
        .map((a) => a.textContent)
    expect(names()).toEqual(['iShares Core S&P 500', 'Demo Emerging Markets', 'Private bond']) // by value, high to low
    const header = within(table).getByRole('columnheader', { name: /Unrealized/ })
    await userEvent.click(within(header).getByRole('button'))
    expect(header).toHaveAttribute('aria-sort', 'ascending')
    expect(names()).toEqual(['Demo Emerging Markets', 'iShares Core S&P 500', 'Private bond']) // -20 first, no value last
    await userEvent.click(within(header).getByRole('button'))
    expect(header).toHaveAttribute('aria-sort', 'descending')
    expect(names()).toEqual(['iShares Core S&P 500', 'Demo Emerging Markets', 'Private bond'])
  })

  it('shows the account column and grouping only when there is more than one account', async () => {
    api()
    renderAt(<Holdings />)
    await screen.findByRole('table')
    expect(screen.queryByRole('columnheader', { name: /Account/ })).toBeNull()
    expect(screen.getByLabelText('Account')).toBeInTheDocument() // the filter is always there
  })

  it('groups by account when asked', async () => {
    api({
      '/api/v1/accounts': [...accounts, { ...accounts[0], id: 2, name: 'Pension' }],
      '/api/v1/positions': {
        positions: [
          position(),
          position({
            account_id: 2,
            account_name: 'Pension',
            instrument_id: 4,
            name: 'Gold ETC',
            ticker: 'SGLD',
          }),
        ],
        totals,
      },
    })
    renderAt(<Holdings />)
    await screen.findByRole('table')
    await userEvent.selectOptions(screen.getByLabelText('Group by'), 'account')
    expect(screen.getAllByRole('rowheader').map((h) => h.textContent)).toEqual([
      'Degiro',
      'Pension',
      'Total',
    ])
  })
})

describe('empty states say what to do next', () => {
  it('asks for the first instrument when there is nothing at all', async () => {
    api(
      {
        '/api/v1/positions': {
          positions: [],
          totals: { ...totals, positions: 0, unvalued_positions: 0 },
        },
      },
      [],
    )
    renderAt(<Holdings />)
    expect(await screen.findByText('No holdings yet')).toBeInTheDocument()
    const buttons = screen.getAllByRole('button', { name: 'Add instrument' })
    expect(buttons.length).toBeGreaterThanOrEqual(2) // the header button and the call to action
  })

  it('asks for the first transaction once instruments exist', async () => {
    api({
      '/api/v1/positions': {
        positions: [],
        totals: { ...totals, positions: 0, unvalued_positions: 0 },
      },
      '/api/v1/instruments': [{ id: 1 }],
    })
    renderAt(<Holdings />)
    const link = await screen.findByRole('link', { name: 'Add a transaction' })
    expect(link).toHaveAttribute('href', '/transactions?add=buy')
  })
})

describe('the instruments tab', () => {
  const instrument = (over: Record<string, unknown> = {}) => ({
    id: 1,
    isin: 'IE00B5BMR087',
    name: 'iShares Core S&P 500',
    asset_class: 'ETF',
    issuer: 'iShares',
    domicile: 'IE',
    ter_pct: null,
    distribution: 'ACC',
    tags: [],
    coupon_pct: null,
    maturity_date: null,
    rating: null,
    status: 'active',
    manual: false,
    listings: [
      { id: 1, mic: 'XETR', ticker: 'SXR8', currency: 'EUR', primary: true, provider_symbols: {} },
    ],
    last_close: { date: '2024-04-10', close: '140', source: 'yahoo', overridden: false },
    stale: true,
    ...over,
  })

  it('lists instruments with their listing, last close and a stale marker', async () => {
    api({
      '/api/v1/instruments': [
        instrument(),
        instrument({
          id: 2,
          name: 'Private bond',
          isin: null,
          manual: true,
          last_close: null,
          stale: false,
          listings: [],
        }),
      ],
    })
    renderAt(<Holdings />)
    await userEvent.click(await screen.findByRole('tab', { name: 'Instruments' }))
    const table = await screen.findByRole('table', { name: /instruments you have added/i })
    const row = within(table).getByRole('link', { name: 'iShares Core S&P 500' }).closest('tr')!
    expect(row).toHaveTextContent('SXR8 · XETR · EUR')
    expect(row).toHaveTextContent('€140.00')
    expect(within(row).getByText('Stale')).toBeInTheDocument()
    const manual = within(table).getByRole('link', { name: 'Private bond' }).closest('tr')!
    expect(within(manual).getByText('Hand-priced')).toBeInTheDocument()
    expect(within(manual).getByRole('button', { name: 'Enter price' })).toBeInTheDocument()
    expect(within(row).queryByRole('button', { name: 'Enter price' })).toBeNull() // only for hand-priced ones
  })

  it('shows the transactions that block a delete', async () => {
    const { calls } = api({
      '/api/v1/instruments': [instrument()],
      'DELETE /api/v1/instruments/1': problem(409, 'Instrument in use', 'cannot be deleted', {
        blocking_total: 2,
        blocking_transactions: [
          { id: 7, type: 'buy', trade_date: '2024-01-02', account: 'Degiro', quantity: '10' },
          { id: 9, type: 'sell', trade_date: '2024-03-01', account: 'Degiro', quantity: '8' },
        ],
      }),
    })
    renderAt(<Holdings />)
    await userEvent.click(await screen.findByRole('tab', { name: 'Instruments' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Delete' }))
    const dialog = await screen.findByRole('dialog', { name: 'Delete' })
    expect(dialog).toHaveTextContent('iShares Core S&P 500 is used by 2 transaction(s):')
    expect(dialog).toHaveTextContent('2024-01-02 · buy · 10 · Degiro')
    expect(dialog).toHaveTextContent('2024-03-01 · sell · 8 · Degiro')
    expect(calls.some((c) => c.method === 'DELETE')).toBe(true)
  })

  it('archives and restores through the status button', async () => {
    const { calls } = api({
      '/api/v1/instruments': [instrument()],
      'PATCH /api/v1/instruments/1': instrument({ status: 'archived' }),
    })
    renderAt(<Holdings />)
    await userEvent.click(await screen.findByRole('tab', { name: 'Instruments' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Archive' }))
    await waitFor(() =>
      expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ status: 'archived' }),
    )
  })
})
