import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AccountsTab } from './components/AccountsTab'
import { Home } from './pages/Home'
import { Insights } from './pages/Insights'
import { System } from './pages/System'
import { GENERAL_US, mockApi, renderAt } from './test-utils'

afterEach(() => vi.unstubAllGlobals())

const ACCOUNT = {
  id: 1,
  name: 'Degiro',
  broker: 'Degiro',
  cost_basis_method: 'FIFO',
  base_currency: 'EUR',
  active: true,
  track_cash: false,
  transaction_count: 3,
}

const SUMMARY = {
  account_id: null,
  as_of: '2025-03-03',
  price_date: '2025-03-03',
  value_eur: '12500.00',
  net_contributions_eur: '10000.00',
  income_eur: '50.00',
  costs_eur: '5.00',
  cash_eur: null,
  total_pnl_eur: '2545.00',
  total_pnl_ratio: '0.2545',
  day_change: { pnl_eur: '-30.00', pnl_ratio: '-0.0024' },
  unvalued_positions: 0,
  period: {
    key: 'YTD',
    start: '2025-01-01',
    end: '2025-03-03',
    value_start_eur: '11000.00',
    value_end_eur: '12500.00',
    net_flows_eur: '500.00',
    income_eur: '50.00',
    costs_eur: '5.00',
    pnl_eur: '1000.00',
    pnl_ratio: '0.0909',
  },
}

describe('Home', () => {
  it('tells a new owner what to do first', async () => {
    mockApi({
      '/api/v1/settings/general': GENERAL_US,
      '/api/v1/accounts': [{ ...ACCOUNT, transaction_count: 0 }],
    })
    renderAt(<Home />)
    expect(
      await screen.findByText('Add your first instrument to start tracking your portfolio.'),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Import a CSV' })).toBeInTheDocument()
  })

  it('shows value, result and the period figures, and reloads when the period changes', async () => {
    const { calls } = mockApi({
      '/api/v1/settings/general': GENERAL_US,
      '/api/v1/accounts': [ACCOUNT],
      '/api/v1/portfolio/summary': SUMMARY,
    })
    renderAt(<Home />)
    expect(await screen.findByText('€12,500.00')).toBeInTheDocument()
    expect(screen.getByText('€10,000.00')).toBeInTheDocument()
    expect(screen.getByText('2025-01-01 to 2025-03-03')).toBeInTheDocument()
    expect(screen.getByText('Prices of 2025-03-03')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: '1 month' }))
    await waitFor(() =>
      expect(calls.some((c) => c.path === '/api/v1/portfolio/summary')).toBe(true),
    )
    await waitFor(() =>
      expect(screen.getByRole('button', { name: '1 month' })).toHaveAttribute(
        'aria-pressed',
        'true',
      ),
    )
  })

  it('warns about holdings that have no price and are left out', async () => {
    mockApi({
      '/api/v1/settings/general': GENERAL_US,
      '/api/v1/accounts': [ACCOUNT],
      '/api/v1/portfolio/summary': { ...SUMMARY, unvalued_positions: 2 },
    })
    renderAt(<Home />)
    expect(
      await screen.findByText('2 holdings have no price yet and are left out of the value.'),
    ).toBeInTheDocument()
  })

  it('does not ask the server for a custom period before both dates are chosen', async () => {
    const { calls } = mockApi({
      '/api/v1/settings/general': GENERAL_US,
      '/api/v1/accounts': [ACCOUNT],
      '/api/v1/portfolio/summary': SUMMARY,
    })
    renderAt(<Home />)
    await screen.findByText('€12,500.00')
    const before = calls.filter((c) => c.path === '/api/v1/portfolio/summary').length
    await userEvent.click(screen.getByRole('button', { name: 'Custom' }))
    expect(screen.getByText(/Pick a start and an end date/)).toBeInTheDocument()
    expect(calls.filter((c) => c.path === '/api/v1/portfolio/summary')).toHaveLength(before + 1) // the query key changed once; no valid dates yet
  })
})

describe('Insights', () => {
  const split = {
    id: 4,
    instrument_id: 1,
    instrument_name: 'Acme Corp',
    isin: null,
    ticker: 'ACME',
    type: 'split',
    ex_date: '2025-03-01',
    ratio: '4.000000',
    status: 'proposed',
    source: 'yahoo',
    applied_at: null,
    transaction_ids: [],
    effects: [
      {
        account_id: 1,
        account_name: 'Degiro',
        quantity_before: '10',
        quantity_after: '40',
        cost_basis_eur: '1000.00',
      },
    ],
  }
  const draft = {
    id: 21,
    type: 'dividend',
    status: 'draft',
    trade_date: '2025-02-20',
    instrument_name: 'Acme Corp',
    account_name: 'Degiro',
    quantity: '10',
    net_amount_eur: '12.50',
  }

  it('shows what a split does to each account and confirms it', async () => {
    const { calls } = mockApi({
      '/api/v1/settings/general': GENERAL_US,
      '/api/v1/corporate-actions': [split],
      '/api/v1/transactions': { items: [], next_cursor: null },
      'POST /api/v1/corporate-actions/4/confirm': { ...split, status: 'applied' },
    })
    renderAt(<Insights />)
    expect(
      await screen.findByText('Degiro: 10 to 40 units, cost basis stays €1,000.00'),
    ).toBeInTheDocument()
    expect(screen.getByText('4 new units per old unit')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Confirm Acme Corp' }))
    await waitFor(() =>
      expect(
        calls.some((c) => c.method === 'POST' && c.path === '/api/v1/corporate-actions/4/confirm'),
      ).toBe(true),
    )
  })

  it('confirms a proposed dividend as proposed, or with a corrected amount', async () => {
    const { calls } = mockApi({
      '/api/v1/settings/general': GENERAL_US,
      '/api/v1/corporate-actions': [],
      '/api/v1/transactions': { items: [draft], next_cursor: null },
      'POST /api/v1/transactions/21/confirm': { ...draft, status: 'posted' },
    })
    renderAt(<Insights />)
    const amount = await screen.findByLabelText('Amount in euro for Acme Corp')
    expect(amount).toHaveValue('12.5')
    await userEvent.clear(amount)
    await userEvent.type(amount, '11.80')
    await userEvent.click(screen.getByRole('button', { name: 'Confirm Acme Corp' }))
    await waitFor(() =>
      expect(calls.some((c) => c.path === '/api/v1/transactions/21/confirm')).toBe(true),
    )
    expect(calls.find((c) => c.path === '/api/v1/transactions/21/confirm')?.body).toEqual({
      net_amount_eur: '11.80',
    })
  })
})

describe('System', () => {
  it('shows provider usage against the budget and queues a refresh', async () => {
    const { calls } = mockApi({
      '/api/v1/system/usage': [
        {
          provider: 'eodhd',
          calls_today: 12,
          daily_budget: 20,
          remaining: 8,
          enabled: true,
          has_key: false,
        },
        {
          provider: 'yahoo',
          calls_today: 3,
          daily_budget: null,
          remaining: null,
          enabled: true,
          has_key: null,
        },
      ],
      '/api/v1/system/jobs': { available: { refresh: [] }, requests: [], runs: [] },
      '/api/v1/audit': { items: [], next_cursor: null },
      'POST /api/v1/system/jobs/refresh/run': {
        id: 1,
        job: 'refresh',
        params: {},
        status: 'pending',
        created_at: '2025-03-03T10:00:00Z',
        finished_at: null,
        error: null,
      },
    })
    renderAt(<System />)
    const usage = await screen.findByRole('table', { name: 'Calls made today per provider' })
    const eodhd = await within(usage).findByRole('row', { name: /eodhd/i })
    expect(eodhd).toHaveTextContent('12')
    expect(eodhd).toHaveTextContent('20')
    expect(eodhd).toHaveTextContent('No key')
    expect(within(usage).getByRole('row', { name: /yahoo/i })).toHaveTextContent('No limit')

    await userEvent.click(screen.getByRole('button', { name: 'Refresh prices now' }))
    expect(await screen.findByText(/Asked the worker to refresh prices/)).toBeInTheDocument()
    expect(
      calls.some((c) => c.method === 'POST' && c.path === '/api/v1/system/jobs/refresh/run'),
    ).toBe(true)
  })

  it('reads an audit entry as before and after', async () => {
    mockApi({
      '/api/v1/system/usage': [],
      '/api/v1/system/jobs': { available: {}, requests: [], runs: [] },
      '/api/v1/audit': {
        items: [
          {
            id: 1,
            ts: '2025-03-03T10:00:00Z',
            actor: 'user',
            entity: 'transaction',
            entity_id: '9',
            action: 'update',
            diff: { quantity: { old: '10', new: '12' } },
          },
        ],
        next_cursor: null,
      },
    })
    renderAt(<System />)
    const log = await screen.findByRole('table', { name: /Changes made to your data/ })
    const row = await within(log).findByRole('row', { name: /transaction #9/ })
    expect(row).toHaveTextContent('quantity: before 10 after 12')
  })
})

describe('Accounts', () => {
  it('asks before switching cost basis method, and sends nothing when declined', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const { calls } = mockApi({ '/api/v1/accounts': [ACCOUNT] })
    renderAt(<AccountsTab />)
    await userEvent.click(await screen.findByRole('button', { name: 'Edit' }))
    await userEvent.selectOptions(screen.getByLabelText('Cost basis method'), 'AVG')
    await userEvent.click(screen.getByRole('button', { name: 'Save account' }))
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('recalculates every lot'))
    expect(calls.some((c) => c.method === 'PATCH')).toBe(false)
  })

  it('sends only what changed once the owner agrees', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const { calls } = mockApi({
      '/api/v1/accounts': [ACCOUNT],
      'PATCH /api/v1/accounts/1': { ...ACCOUNT, cost_basis_method: 'AVG' },
    })
    renderAt(<AccountsTab />)
    await userEvent.click(await screen.findByRole('button', { name: 'Edit' }))
    await userEvent.selectOptions(screen.getByLabelText('Cost basis method'), 'AVG')
    await userEvent.click(screen.getByRole('button', { name: 'Save account' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true))
    expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ cost_basis_method: 'AVG' })
  })

  it('warns before cash tracking is switched on and sends only that change', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const { calls } = mockApi({
      '/api/v1/accounts': [ACCOUNT],
      'PATCH /api/v1/accounts/1': { ...ACCOUNT, track_cash: true },
    })
    renderAt(<AccountsTab />)
    await userEvent.click(await screen.findByRole('button', { name: 'Edit' }))
    await userEvent.click(screen.getByLabelText('Track cash in this account'))
    await userEvent.click(screen.getByRole('button', { name: 'Save account' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true))
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('opening deposit'))
    expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ track_cash: true })
  })
})
