import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { QuickAdd } from './components/QuickAdd'
import { parseBrokerRows, Reconcile } from './components/Reconcile'
import { Reports } from './pages/Reports'
import { GENERAL_US, mockApi, problem, renderAt } from './test-utils'

afterEach(() => vi.unstubAllGlobals())

const instrument = (id: number, name: string, close: string | null) => ({
  id,
  name,
  isin: null,
  asset_class: 'ETF',
  status: 'active',
  manual: false,
  listings: [],
  last_close: close ? { date: '2026-10-02', close, source: 'yahoo' } : null,
  stale: false,
  tags: [],
})

const base = {
  '/api/v1/settings/general': GENERAL_US,
  '/api/v1/accounts': [
    { id: 1, name: 'Degiro', broker: null, cost_basis_method: 'FIFO', active: true },
  ],
  '/api/v1/instruments': [
    instrument(1, 'Demo World ETF', '50'),
    instrument(2, 'Demo Gold ETC', '100'),
  ],
}

async function chooseRow(n: number, name: string) {
  const group = screen.getByRole('group', { name: `Buy ${n}` })
  await within(group).findByRole('option', { name })
  await userEvent.selectOptions(within(group).getByLabelText('Instrument'), name)
  return group
}

describe('quick add (FR-TX-11)', () => {
  it('splits an amount over the rows in whole units and saves them as one batch', async () => {
    const { calls } = mockApi({
      ...base,
      'POST /api/v1/transactions/batch': { created: [] },
    })
    renderAt(<QuickAdd open onClose={() => undefined} />)
    const first = await chooseRow(1, 'Demo World ETF') // priced at 50 from the last close
    const second = await chooseRow(2, 'Demo Gold ETC') // priced at 100
    await userEvent.type(screen.getByLabelText('Amount to spend (EUR)'), '1000')
    await userEvent.type(within(first).getByLabelText('Share (%)'), '70')
    await userEvent.type(within(second).getByLabelText('Share (%)'), '30')
    await userEvent.click(screen.getByRole('button', { name: 'Split the amount' }))
    expect(within(first).getByLabelText('Units')).toHaveValue('14') // 700 / 50
    expect(within(second).getByLabelText('Units')).toHaveValue('3') // 300 / 100
    await userEvent.click(screen.getByRole('button', { name: 'Save all' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    const body = calls.find((c) => c.method === 'POST')?.body as {
      transactions: Record<string, unknown>[]
    }
    expect(body.transactions).toHaveLength(2)
    expect(body.transactions[0]).toMatchObject({
      account_id: 1,
      type: 'buy',
      instrument_id: 1,
      quantity: '14',
      price: '50',
      fees: '0',
    })
    expect(body.transactions[1]).toMatchObject({ instrument_id: 2, quantity: '3', price: '100' })
  })

  it('refuses fractional units and names the row, without calling the server', async () => {
    const { calls } = mockApi(base)
    renderAt(<QuickAdd open onClose={() => undefined} />)
    const first = await chooseRow(1, 'Demo World ETF')
    await userEvent.type(within(first).getByLabelText('Units'), '2.5')
    await userEvent.click(screen.getByRole('button', { name: 'Save all' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Row 1: enter whole units, at least 1.',
    )
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
  })

  it('shows every problem the server found, each with its row', async () => {
    mockApi({
      ...base,
      'POST /api/v1/transactions/batch': () =>
        problem(422, 'Cannot save transaction', 'Nothing was saved: 1 of 2 rows need fixing.', {
          errors: [{ field: 'rows.2.price', message: 'Row 2: A trade needs a price.' }],
        }),
    })
    renderAt(<QuickAdd open onClose={() => undefined} />)
    const first = await chooseRow(1, 'Demo World ETF')
    await userEvent.type(within(first).getByLabelText('Units'), '2')
    await userEvent.click(screen.getByRole('button', { name: 'Save all' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Nothing was saved')
    expect(alert).toHaveTextContent('Row 2: A trade needs a price.')
  })
})

describe('reconcile (FR-TX-10)', () => {
  it('reads pasted lines whatever separates the fields, and reports the ones it cannot read', () => {
    const { rows, unreadable } = parseBrokerRows(
      [
        'IE00DEMO0001\t12',
        'ie00demo0002;5,5',
        'Demo ETF   IE00DEMO0003   7   EUR',
        'nonsense',
        '',
      ].join('\n'),
    )
    expect(rows).toEqual([
      { isin: 'IE00DEMO0001', quantity: '12' },
      { isin: 'IE00DEMO0002', quantity: '5.5' },
      { isin: 'IE00DEMO0003', quantity: '7' },
    ])
    expect(unreadable).toEqual(['nonsense'])
  })

  it('lists the differences with the ledger and links to the transactions', async () => {
    const { calls } = mockApi({
      ...base,
      'POST /api/v1/transactions/reconcile': {
        account_id: 1,
        date: '2026-10-02',
        matches: 1,
        differences: 2,
        lines: [
          {
            instrument_id: 2,
            name: 'Demo Gold ETC',
            isin: 'IE00DEMO0002',
            ours: '3',
            broker: '5',
            difference: '2',
            status: 'difference',
          },
          {
            instrument_id: null,
            name: 'IE00DEMO0009',
            isin: 'IE00DEMO0009',
            ours: '0',
            broker: '4',
            difference: '4',
            status: 'unknown',
          },
          {
            instrument_id: 1,
            name: 'Demo World ETF',
            isin: 'IE00DEMO0001',
            ours: '12',
            broker: '12',
            difference: '0',
            status: 'match',
          },
        ],
      },
    })
    renderAt(<Reconcile open onClose={() => undefined} />)
    await userEvent.type(
      await screen.findByLabelText('Holdings from your broker'),
      'IE00DEMO0001\t12',
    )
    await userEvent.click(screen.getByRole('button', { name: 'Compare' }))
    expect(await screen.findByRole('status')).toHaveTextContent('2 lines differ; 1 match.')
    const table = screen.getByRole('table', { name: 'Result of the comparison' })
    const gold = within(table).getByText('Demo Gold ETC').closest('tr') as HTMLElement
    expect(gold).toHaveTextContent('Differs')
    expect(within(gold).getByRole('link', { name: 'Show transactions' })).toHaveAttribute(
      'href',
      '/transactions?instrument=2',
    )
    const unknown = within(table).getByText('IE00DEMO0009', { selector: 'td' })
    expect(unknown.closest('tr')).toHaveTextContent('Not in Folio')
    const sent = calls.find((c) => c.path === '/api/v1/transactions/reconcile')
    expect(sent?.body).toMatchObject({
      account_id: 1,
      rows: [{ isin: 'IE00DEMO0001', quantity: '12' }],
    })
  })

  it('asks for something to compare when nothing was pasted', async () => {
    const { calls } = mockApi(base)
    renderAt(<Reconcile open onClose={() => undefined} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Compare' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Paste at least one line')
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
  })
})

describe('reports (FR-TX-12)', () => {
  const report = {
    year: 2025,
    realized: [
      {
        account: 'Degiro',
        instrument: 'Demo US Tech Stock',
        isin: null,
        quantity: '3',
        proceeds_eur: '600',
        cost_eur: '450',
        result_eur: '150',
      },
    ],
    income: [
      {
        account: 'Degiro',
        instrument: 'Demo Bond Fund',
        isin: null,
        gross_eur: '20',
        withholding_eur: '3',
        net_eur: '17',
      },
    ],
    realized_total_eur: '150',
    income_gross_eur: '20',
    withholding_eur: '3',
    costs_eur: '4',
  }

  it('shows the year with sales and income, and offers the CSV for that selection', async () => {
    mockApi({
      ...base,
      '/api/v1/reports/years': [2025, 2024],
      '/api/v1/reports/realized': report,
    })
    renderAt(<Reports />)
    const sales = await screen.findByRole('table', { name: 'Sales' })
    expect(within(sales).getByRole('row', { name: /Demo US Tech Stock/ })).toHaveTextContent(
      /150[.,]00/,
    )
    expect(screen.getByRole('table', { name: 'Dividends and interest' })).toHaveTextContent(
      'Demo Bond Fund',
    )
    expect(screen.getByRole('link', { name: 'Download CSV' })).toHaveAttribute(
      'href',
      '/api/v1/reports/realized?year=2025&format=csv',
    )
    await userEvent.selectOptions(screen.getByLabelText('Account'), 'Degiro')
    await waitFor(() =>
      expect(screen.getByRole('link', { name: 'Download CSV' })).toHaveAttribute(
        'href',
        '/api/v1/reports/realized?year=2025&format=csv&account=1',
      ),
    )
  })

  it('says what it needs when there is nothing to report', async () => {
    mockApi({ ...base, '/api/v1/reports/years': [] })
    renderAt(<Reports />)
    expect(await screen.findByText('No reports yet')).toBeInTheDocument()
  })
})
