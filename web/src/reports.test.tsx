import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Reports } from './pages/Reports'
import { GENERAL_US, mockApi, renderAt } from './test-utils'

afterEach(() => vi.unstubAllGlobals())

const REPORT = (over: Record<string, unknown> = {}) => ({
  year: 2024,
  start: '2024-01-01',
  end: '2024-12-31',
  partial: false,
  value_start_eur: '1050',
  value_end_eur: '375',
  unvalued_start: 0,
  unvalued_end: 0,
  money_in_eur: '550',
  money_out_eur: '1517',
  net_contributions_eur: '-967',
  income_gross_eur: '25',
  withholding_eur: '3',
  income_net_eur: '22',
  trade_costs_eur: '3',
  other_costs_eur: '2.5',
  realized_proceeds_eur: '1517',
  realized_cost_eur: '1221',
  realized_result_eur: '296',
  unrealized_start_eur: '49',
  unrealized_end_eur: '45',
  unrealized_change_eur: '-4',
  holdings_start: [
    {
      account: 'Degiro',
      instrument: 'F fund',
      isin: 'IE00B5BMR087',
      quantity: '10',
      value_eur: '1050',
      cost_basis_eur: '1001',
    },
  ],
  holdings_end: [
    {
      account: 'Degiro',
      instrument: 'F fund',
      isin: 'IE00B5BMR087',
      quantity: '3',
      value_eur: null,
      cost_basis_eur: '330',
    },
  ],
  note: 'Support for filling in a tax return, not tax advice.',
  ...over,
})

const routes = (extra: Record<string, unknown> = {}) => ({
  '/api/v1/settings/general': GENERAL_US,
  '/api/v1/reports/years': [2024],
  '/api/v1/reports/tax-years': [2025, 2024],
  '/api/v1/reports/tax-support': REPORT(),
  '/api/v1/accounts': [
    {
      id: 1,
      name: 'Degiro',
      broker: 'Degiro',
      cost_basis_method: 'FIFO',
      base_currency: 'EUR',
      active: true,
      transaction_count: 3,
    },
  ],
  ...extra,
})

describe('the tax-support report (FR-PF-11)', () => {
  it('shows what a tax return asks for, with the holdings on both dates', async () => {
    mockApi(routes())
    renderAt(<Reports />, '/reports?tab=tax')
    const table = await screen.findByRole('table', { name: 'Figures for 2025 for a tax return' })
    const line = (label: RegExp) => within(table).getByRole('row', { name: label })
    expect(line(/Value on 2024-01-01/)).toHaveTextContent('€1,050.00')
    expect(line(/Value on 2024-12-31/)).toHaveTextContent('€375.00')
    expect(line(/Money put in/)).toHaveTextContent('€550.00')
    expect(line(/Money taken out/)).toHaveTextContent('€1,517.00')
    expect(line(/Tax and fees withheld/)).toHaveTextContent('€3.00')
    expect(line(/Costs of buying and selling/)).toHaveTextContent('€3.00')
    expect(line(/^Realized result/)).toHaveTextContent('€296.00')
    expect(line(/Change in unrealized result/)).toHaveTextContent('€4.00')
    const start = screen.getByRole('table', { name: 'Holdings on 2024-01-01' })
    expect(within(start).getByRole('row', { name: /F fund/ })).toHaveTextContent('€1,050.00')
    const end = screen.getByRole('table', { name: 'Holdings on 2024-12-31' })
    expect(within(end).getByRole('row', { name: /F fund/ })).toHaveTextContent('–') // no price
    expect(screen.getByText(/not tax advice/)).toBeInTheDocument()
  })

  it('offers the CSV for the chosen year and account, and prints', async () => {
    const print = vi.fn()
    vi.stubGlobal('print', print)
    mockApi(routes())
    renderAt(<Reports />, '/reports?tab=tax')
    const download = await screen.findByRole('link', { name: 'Download CSV' })
    expect(download).toHaveAttribute('href', '/api/v1/reports/tax-support?year=2025&format=csv')
    await userEvent.selectOptions(screen.getByLabelText('Year'), '2024')
    await userEvent.selectOptions(await screen.findByLabelText('Account'), '1')
    expect(screen.getByRole('link', { name: 'Download CSV' })).toHaveAttribute(
      'href',
      '/api/v1/reports/tax-support?year=2024&format=csv&account=1',
    )
    await userEvent.click(screen.getByRole('button', { name: 'Print or save as PDF' }))
    expect(print).toHaveBeenCalledOnce()
  })

  it('says when the year is not over, and when holdings had no price', async () => {
    mockApi(
      routes({
        '/api/v1/reports/tax-support': REPORT({
          partial: true,
          end: '2026-10-06',
          unvalued_end: 2,
        }),
      }),
    )
    renderAt(<Reports />, '/reports?tab=tax')
    expect(
      await screen.findByText('The year is not over: the figures run to 2026-10-06.'),
    ).toBeInTheDocument()
    expect(screen.getByText(/2 holding\(s\) had no price/)).toBeInTheDocument()
  })

  it('says so when there is nothing to report yet', async () => {
    mockApi(routes({ '/api/v1/reports/tax-years': [] }))
    renderAt(<Reports />, '/reports?tab=tax')
    expect(await screen.findByText('No transactions yet')).toBeInTheDocument()
  })
})

describe('the export tab (FR-TX-13)', () => {
  it('links to the four downloads and follows the chosen account', async () => {
    mockApi(routes())
    renderAt(<Reports />, '/reports?tab=export')
    const links = await screen.findAllByRole('link', { name: /Download/ })
    expect(links.map((a) => a.getAttribute('href'))).toEqual([
      '/api/v1/export/transactions?format=csv',
      '/api/v1/export/transactions?format=json',
      '/api/v1/export/positions?format=csv',
      '/api/v1/export/positions?format=json',
    ])
    await userEvent.selectOptions(await screen.findByLabelText('Account'), '1')
    expect(
      screen.getAllByRole('link', { name: /Download/ }).map((a) => a.getAttribute('href')),
    ).toContain('/api/v1/export/transactions?format=csv&account=1')
    expect(screen.getByText(/import the file again/)).toBeInTheDocument()
  })
})

describe('the tabs', () => {
  it('opens on the realized result and switches', async () => {
    mockApi({
      ...routes(),
      '/api/v1/reports/realized': {
        year: 2024,
        realized: [],
        income: [],
        realized_total_eur: '0',
        income_gross_eur: '0',
        withholding_eur: '0',
        costs_eur: '0',
      },
    })
    renderAt(<Reports />, '/reports')
    expect(await screen.findByText('Realized result', { selector: 'dt' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: 'Export' }))
    expect(await screen.findByText('Positions')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Export' })).toHaveAttribute('aria-selected', 'true')
  })
})
