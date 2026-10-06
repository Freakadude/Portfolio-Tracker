import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { PositionDetail } from './pages/PositionDetail'
import { GENERAL_US, mockApi, problem, renderAt } from './test-utils'

// The chart draws on a canvas, which jsdom does not have: record what it is asked to draw.
const chart = vi.hoisted(() => ({
  series: { setData: vi.fn() },
  timeScale: { fitContent: vi.fn(), setVisibleRange: vi.fn() },
  remove: vi.fn(),
  markers: vi.fn(),
  created: vi.fn(),
}))
vi.mock('lightweight-charts', () => ({
  ColorType: { Solid: 'solid' },
  LineSeries: 'line',
  createChart: (...args: unknown[]) => {
    chart.created(...args)
    return {
      addSeries: () => chart.series,
      timeScale: () => chart.timeScale,
      remove: chart.remove,
    }
  },
  createSeriesMarkers: (_series: unknown, markers: unknown) => chart.markers(markers),
}))

const detail = (over: Record<string, unknown> = {}) => ({
  instrument: {
    id: 1,
    isin: 'IE00B5BMR087',
    name: 'iShares Core S&P 500',
    asset_class: 'ETF',
    ticker: 'SXR8',
    currency: 'EUR',
    issuer: 'iShares',
    product_url: null,
  },
  account_id: null,
  as_of: null,
  summary: {
    quantity: '5',
    avg_cost_eur: '120.1',
    cost_basis_eur: '600.5',
    market_value_eur: '700',
    unrealized_pnl_eur: '99.5',
    unrealized_ratio: '0.1657',
    realized_pnl_eur: '346.5',
    income_eur: '3',
    total_return_eur: '449',
    total_return_ratio: '0.2039',
    day_change_eur: '10',
    day_change_ratio: '0.0145',
    weight: '0.6',
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
  },
  lots: [
    {
      buy_transaction_id: 2,
      account_id: 1,
      trade_date: '2024-02-01',
      open_quantity: '5',
      cost_eur: '600.5',
      avg_cost_eur: '120.1',
      market_value_eur: '700',
      unrealized_pnl_eur: '99.5',
      unrealized_ratio: '0.1657',
    },
  ],
  matches: [
    {
      sell_transaction_id: 3,
      sell_date: '2024-03-01',
      lot_buy_transaction_id: 1,
      account_id: 1,
      quantity: '10',
      cost_eur: '1001',
      proceeds_eur: '1298.67',
      realized_pnl_eur: '297.67',
    },
    {
      sell_transaction_id: 3,
      sell_date: '2024-03-01',
      lot_buy_transaction_id: 2,
      account_id: 1,
      quantity: '5',
      cost_eur: '600.5',
      proceeds_eur: '649.33',
      realized_pnl_eur: '48.83',
    },
  ],
  transactions: [
    {
      id: 3,
      type: 'sell',
      trade_date: '2024-03-01',
      quantity: '15',
      price: '130',
      currency: 'EUR',
      net_amount_eur: '1948',
    },
    {
      id: 2,
      type: 'buy',
      trade_date: '2024-02-01',
      quantity: '10',
      price: '120',
      currency: 'EUR',
      net_amount_eur: '-1201',
    },
    {
      id: 1,
      type: 'buy',
      trade_date: '2024-01-02',
      quantity: '10',
      price: '100',
      currency: 'EUR',
      net_amount_eur: '-1001',
    },
  ],
  ...over,
})

const prices = [
  { date: '2024-01-02', close: '100' },
  { date: '2024-01-03', close: '101' },
  { date: '2024-02-01', close: '120' },
  { date: '2024-03-01', close: '130' },
  { date: '2024-04-10', close: '140' },
]

beforeEach(() => vi.clearAllMocks())
afterEach(() => vi.unstubAllGlobals())

function show(detailBody: unknown = detail(), priceRows: unknown = prices) {
  mockApi({
    '/api/v1/settings/general': GENERAL_US,
    '/api/v1/positions/1': detailBody,
    '/api/v1/instruments/1/prices': priceRows,
  })
  return renderAt(<PositionDetail />, '/holdings/1', '/holdings/:instrumentId')
}

describe('position detail', () => {
  it('shows the holding, lots, how realized results arose, and the history', async () => {
    show()
    expect(await screen.findByRole('heading', { name: 'iShares Core S&P 500' })).toBeInTheDocument()
    expect(screen.getByText('SXR8 · IE00B5BMR087 · ETF')).toBeInTheDocument()
    const stat = (label: string) => screen.getByText(label).closest('div')!
    expect(stat('Cost basis')).toHaveTextContent('€600.50')
    expect(stat('Market value')).toHaveTextContent('€700.00')
    expect(stat('Unrealized result')).toHaveTextContent('+€99.50 ▲')
    expect(stat('Total return')).toHaveTextContent('+€449.00 ▲')
    expect(stat('Latest close')).toHaveTextContent('€140.00')
    expect(stat('First purchase')).toHaveTextContent('2024-01-02')

    const lots = screen.getByRole('table', { name: /open lots/i })
    expect(within(lots).getAllByRole('row')).toHaveLength(2) // header + the one lot that remains
    expect(lots).toHaveTextContent('2024-02-01')

    const history = screen.getByRole('heading', { name: 'Transactions' }).closest('section')!
    expect(
      within(history)
        .getAllByRole('row')
        .map((r) => r.textContent),
    ).toEqual([
      expect.stringContaining('Date'),
      expect.stringContaining('Sell'),
      expect.stringContaining('Buy'),
      expect.stringContaining('Buy'),
    ])
    const matches = screen
      .getByRole('heading', { name: 'How realized results arose' })
      .closest('section')!
    expect(matches).toHaveTextContent('+€297.67 ▲')
  })

  it('links to buying and selling pre-filled for this instrument', async () => {
    show()
    expect(await screen.findByRole('link', { name: 'Buy' })).toHaveAttribute(
      'href',
      '/transactions?add=buy&instrument=1',
    )
    expect(screen.getByRole('link', { name: 'Sell' })).toHaveAttribute(
      'href',
      '/transactions?add=sell&instrument=1',
    )
  })

  it('offers no Sell for something you do not hold', async () => {
    const d = detail()
    show({ ...d, summary: { ...d.summary, quantity: '0', market_value_eur: '0' }, lots: [] })
    await screen.findByRole('link', { name: 'Buy' })
    expect(screen.queryByRole('link', { name: 'Sell' })).toBeNull()
  })

  it('draws the price line and puts buy and sell markers on days that have a price', async () => {
    show()
    await screen.findByRole('img', { name: /Price chart: iShares Core S&P 500/ })
    expect(chart.series.setData).toHaveBeenCalledWith([
      { time: '2024-01-02', value: 100 },
      { time: '2024-01-03', value: 101 },
      { time: '2024-02-01', value: 120 },
      { time: '2024-03-01', value: 130 },
      { time: '2024-04-10', value: 140 },
    ])
    const markers = chart.markers.mock.calls[0][0] as {
      time: string
      shape: string
      text: string
    }[]
    expect(markers.map((m) => [m.time, m.shape, m.text])).toEqual([
      ['2024-01-02', 'arrowUp', 'Buy'],
      ['2024-02-01', 'arrowUp', 'Buy'],
      ['2024-03-01', 'arrowDown', 'Sell'],
    ])
  })

  it('snaps a trade on a day without a close to the close before it', async () => {
    const d = detail()
    show({ ...d, transactions: [{ ...d.transactions[1], trade_date: '2024-02-03' }] }) // a Saturday
    await screen.findByRole('img')
    const markers = chart.markers.mock.calls[0][0] as { time: string }[]
    expect(markers.map((m) => m.time)).toEqual(['2024-02-01'])
  })

  it('offers the same data as a table for anyone who cannot use the chart', async () => {
    show()
    await userEvent.click(await screen.findByRole('button', { name: 'Show data as a table' }))
    const table = screen.getByRole('table', { name: 'Closing prices' })
    expect(
      within(table)
        .getAllByRole('row')
        .map((r) => r.textContent),
    ).toEqual([
      'DateClosing price',
      '2024-04-10€140.00', // newest first
      '2024-03-01€130.00',
      '2024-02-01€120.00',
      '2024-01-03€101.00',
      '2024-01-02€100.00',
    ])
    expect(screen.queryByRole('img')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Show chart' }))
    expect(await screen.findByRole('img')).toBeInTheDocument()
  })

  it('can zoom the chart to a range', async () => {
    show()
    await screen.findByRole('img')
    await userEvent.click(screen.getByRole('button', { name: '3M' }))
    expect(chart.timeScale.setVisibleRange).toHaveBeenLastCalledWith({
      from: '2024-01-09',
      to: '2024-04-10',
    })
    await userEvent.click(screen.getByRole('button', { name: 'Max' }))
    expect(chart.timeScale.fitContent).toHaveBeenCalled()
  })

  it('shows the trading-currency figures next to euros for a foreign listing', async () => {
    const d = detail()
    show({ ...d, instrument: { ...d.instrument, currency: 'USD' } })
    expect(await screen.findByText(/In USD: 700/)).toHaveTextContent('Cost basis 600')
  })

  it('shows the latest refreshed price next to the latest close, or says there is none', async () => {
    const d = detail()
    const quoted = {
      ...d,
      summary: {
        ...d.summary,
        price: {
          ...d.summary.price,
          delayed_price: '141.5',
          delayed_at: '2024-04-11T13:20:00Z',
          delayed_source: 'yahoo',
        },
      },
    }
    const first = show(quoted)
    expect(await screen.findByText('Latest refreshed price')).toBeInTheDocument()
    expect(screen.getByText(/141\.5/)).toBeInTheDocument()
    expect(screen.getByText(/quoted 11 Apr 2024, 15:20/)).toBeInTheDocument()
    first.unmount()
    show()
    expect(await screen.findByText('No quote since the last close')).toBeInTheDocument()
  })

  it('says so when there are no prices yet', async () => {
    show(detail(), [])
    expect(await screen.findByText(/No prices stored yet/)).toBeInTheDocument()
    expect(chart.created).not.toHaveBeenCalled()
  })

  it('explains an unknown instrument', async () => {
    mockApi({
      '/api/v1/settings/general': GENERAL_US,
      '/api/v1/positions/1': problem(404, 'Not found', 'That instrument does not exist.'),
      '/api/v1/instruments/1/prices': [],
    })
    renderAt(<PositionDetail />, '/holdings/1', '/holdings/:instrumentId')
    expect(await screen.findByText('That instrument does not exist.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Back to holdings/ })).toHaveAttribute(
      'href',
      '/holdings',
    )
  })
})

describe('editing a transaction from the position (FR-TX-14)', () => {
  const stored = (id: number, type: string, date: string, qty: string, price: string) => ({
    id,
    account_id: 1,
    account_name: 'Degiro',
    instrument_id: 1,
    instrument_name: 'iShares Core S&P 500',
    ticker: 'SXR8',
    type,
    status: 'posted',
    trade_date: date,
    settle_date: null,
    quantity: qty,
    price,
    currency: 'EUR',
    fx_rate_to_eur: '1',
    fees: '0',
    fees_currency: 'EUR',
    fees_fx_rate_to_eur: '1',
    taxes: '0',
    taxes_currency: 'EUR',
    taxes_fx_rate_to_eur: '1',
    net_amount_eur: '-1001',
    ratio: null,
    note: null,
    source: 'csv',
    external_ref: 'X',
    import_batch_id: 1,
  })
  const withRows = () =>
    detail({
      transactions: [
        stored(2, 'buy', '2024-02-01', '10', '120'),
        stored(1, 'buy', '2024-01-02', '10', '100'),
      ],
    })
  const routes = (body: unknown) => ({
    '/api/v1/settings/general': GENERAL_US,
    '/api/v1/positions/1': body,
    '/api/v1/instruments/1/prices': prices,
    '/api/v1/accounts': [
      {
        id: 1,
        name: 'Degiro',
        broker: 'Degiro',
        cost_basis_method: 'FIFO',
        base_currency: 'EUR',
        active: true,
        transaction_count: 2,
      },
    ],
    '/api/v1/instruments': [],
    'POST /api/v1/transactions/preview-amount': {
      currency: 'EUR',
      fx_rate_to_eur: '1',
      gross_eur: '1100',
      fees_eur: '0',
      taxes_eur: '0',
      net_amount_eur: '-1100',
    },
  })

  it('opens the stored values of a row, saves the change and reloads the position', async () => {
    const { calls } = mockApi({
      ...routes(withRows()),
      'PATCH /api/v1/transactions/1': stored(1, 'buy', '2024-01-02', '10', '110'),
    })
    renderAt(<PositionDetail />, '/holdings/1', '/holdings/:instrumentId')
    await userEvent.click(await screen.findByRole('button', { name: 'Edit the Buy of 2024-01-02' }))
    const dialog = await screen.findByRole('dialog', { name: 'Edit transaction' })
    expect(within(dialog).getByLabelText('Units')).toHaveValue('10')
    expect(within(dialog).getByLabelText('Price per unit')).toHaveValue('100')
    await userEvent.clear(within(dialog).getByLabelText('Price per unit'))
    await userEvent.type(within(dialog).getByLabelText('Price per unit'), '110')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save transaction' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ price: '110' })
    expect(calls.filter((c) => c.path === '/api/v1/positions/1').length).toBeGreaterThan(1)
  })

  it('deletes a row after asking', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const { calls } = mockApi({ ...routes(withRows()), 'DELETE /api/v1/transactions/2': null })
    renderAt(<PositionDetail />, '/holdings/1', '/holdings/:instrumentId')
    await userEvent.click(
      await screen.findByRole('button', { name: 'Delete the Buy of 2024-02-01' }),
    )
    await waitFor(() =>
      expect(calls.some((c) => c.method === 'DELETE' && c.path === '/api/v1/transactions/2')).toBe(
        true,
      ),
    )
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('2024-02-01'))
    confirm.mockRestore()
  })
})

describe('looking the fund up elsewhere', () => {
  const instrument = (over: Record<string, unknown>) =>
    detail({ instrument: { ...detail().instrument, ...over } })

  it('links to the justETF page of the ISIN, in a new tab', async () => {
    show()
    const group = await screen.findByRole('group', { name: 'Look this fund up elsewhere' })
    const link = within(group).getByRole('link', { name: /justETF page/ })
    expect(link).toHaveAttribute(
      'href',
      'https://www.justetf.com/en/etf-profile.html?isin=IE00B5BMR087',
    )
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  })

  it('searches for the issuer page until the owner has saved its address', async () => {
    show()
    const group = await screen.findByRole('group', { name: 'Look this fund up elsewhere' })
    const find = within(group).getByRole('link', { name: /Find the issuer's page/ })
    const href = new URL(find.getAttribute('href') ?? '')
    expect(href.hostname).toBe('duckduckgo.com')
    expect(href.searchParams.get('q')).toBe('IE00B5BMR087 iShares iShares Core S&P 500 ETF')
    expect(within(group).queryByRole('link', { name: /Issuer's product page/ })).toBeNull()
  })

  it('goes straight to the saved issuer page', async () => {
    show(instrument({ product_url: 'https://www.ishares.com/nl/producten/253743' }))
    const group = await screen.findByRole('group', { name: 'Look this fund up elsewhere' })
    expect(within(group).getByRole('link', { name: /Issuer's product page/ })).toHaveAttribute(
      'href',
      'https://www.ishares.com/nl/producten/253743',
    )
    expect(within(group).queryByRole('link', { name: /Find the issuer's page/ })).toBeNull()
  })

  it('offers nothing for a share, and no justETF page for a fund it does not list', async () => {
    show(instrument({ asset_class: 'EQUITY', isin: 'US0378331005' }))
    await screen.findByRole('heading', { name: 'iShares Core S&P 500' })
    expect(screen.queryByRole('group', { name: 'Look this fund up elsewhere' })).toBeNull()
  })

  it('shows no justETF page for a mutual fund, only the issuer search', async () => {
    show(instrument({ asset_class: 'FUND' }))
    const group = await screen.findByRole('group', { name: 'Look this fund up elsewhere' })
    expect(within(group).queryByRole('link', { name: /justETF page/ })).toBeNull()
    expect(within(group).getByRole('link', { name: /Find the issuer's page/ })).toBeInTheDocument()
  })
})
