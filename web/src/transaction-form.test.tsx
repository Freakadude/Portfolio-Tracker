import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { TransactionForm, buildBody, fieldsFor } from './components/TransactionForm'
import { GENERAL_US, mockApi, problem, renderAt } from './test-utils'

afterEach(() => vi.unstubAllGlobals())

const ACCOUNT = {
  id: 1,
  name: 'Degiro',
  broker: 'Degiro',
  cost_basis_method: 'FIFO',
  base_currency: 'EUR',
  active: true,
  transaction_count: 0,
}
const listing = (currency: string) => ({
  id: 1,
  mic: 'XNAS',
  ticker: 'ACME',
  currency,
  primary: true,
  provider_symbols: {},
})
const instrument = (id: number, name: string, currency: string) => ({
  id,
  isin: null,
  name,
  asset_class: 'Stock',
  issuer: null,
  domicile: null,
  ter_pct: null,
  distribution: null,
  tags: [],
  coupon_pct: null,
  maturity_date: null,
  rating: null,
  status: 'active',
  manual: true,
  listings: [listing(currency)],
  last_close: null,
  stale: false,
})
const PREVIEW = {
  matches: [
    {
      lot_buy_transaction_id: 7,
      lot_trade_date: '2025-01-10',
      quantity: '4',
      cost_eur: '400.00',
      proceeds_eur: '480.00',
      realized_pnl_eur: '80.00',
    },
  ],
  net_proceeds_eur: '480.00',
  cost_eur: '400.00',
  realized_pnl_eur: '80.00',
  realized_pct: '0.2',
  remaining_quantity: '6',
  remaining_cost_basis_eur: '600.00',
}

const BASE = {
  '/api/v1/settings/general': GENERAL_US,
  '/api/v1/accounts': [ACCOUNT],
  '/api/v1/instruments': [instrument(1, 'Acme Corp', 'USD')],
}

describe('which fields a type needs', () => {
  it('shows units, price and fees for a trade, and an amount for a dividend', () => {
    expect(fieldsFor('buy')).toMatchObject({ units: true, price: true, fees: true, amount: false })
    expect(fieldsFor('dividend')).toMatchObject({ units: false, amount: true, withholding: true })
    expect(fieldsFor('split')).toMatchObject({ ratio: true, units: false })
    expect(fieldsFor('deposit')).toMatchObject({ instrument: false, amount: true })
  })
})

describe('the request body', () => {
  const values = {
    type: 'buy' as const,
    accountId: '1',
    tradeDate: '2025-03-03',
    settleDate: '',
    instrumentId: '1',
    quantity: '10',
    price: '20.5',
    currency: 'USD',
    fxRate: '1.0950',
    fees: '1',
    feesCurrency: 'EUR',
    taxes: '',
    amount: '',
    ratio: '',
    note: '',
  }
  it('turns the broker rate (foreign per euro) into the exact euro-per-unit rate', () => {
    const body = buildBody(values) as unknown as Record<string, unknown>
    expect(body.fx_rate_to_eur).toBe('0.9132420091')
    expect(body.quantity).toBe('10')
    expect(body.instrument_id).toBe(1)
  })
  it('leaves out the rate for euro trades and fields the type does not use', () => {
    const body = buildBody({
      ...values,
      currency: 'EUR',
      type: 'deposit',
      amount: '500',
    }) as unknown as Record<string, unknown>
    expect(body).not.toHaveProperty('fx_rate_to_eur')
    expect(body).not.toHaveProperty('quantity')
    expect(body.net_amount_eur).toBe('500')
  })
})

describe('the form', () => {
  it('asks for required values in plain words before calling the server', async () => {
    const { calls } = mockApi(BASE)
    renderAt(<TransactionForm onDone={vi.fn()} />)
    await screen.findByRole('option', { name: /Acme Corp/ })
    await userEvent.click(screen.getByRole('button', { name: 'Save transaction' }))
    expect(await screen.findAllByText('This is required.')).not.toHaveLength(0)
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
  })

  it('keeps its defaults when a prefill field is undefined (the page passes what the link lacks)', async () => {
    mockApi(BASE)
    renderAt(
      <TransactionForm onDone={vi.fn()} initial={{ type: undefined, instrumentId: undefined }} />,
    )
    expect(await screen.findByLabelText('Instrument')).toBeInTheDocument()
    expect(screen.getByLabelText('Type')).toHaveValue('buy')
  })

  it('shows the lots a sale uses, live, and saves it', async () => {
    const { calls } = mockApi({
      ...BASE,
      'POST /api/v1/transactions/preview-sell': PREVIEW,
      'POST /api/v1/transactions': { id: 9 },
    })
    const onDone = vi.fn()
    renderAt(<TransactionForm onDone={onDone} initial={{ type: 'sell' }} />)
    await screen.findByRole('option', { name: /Acme Corp/ })
    await userEvent.selectOptions(screen.getByLabelText('Instrument'), '1')
    await userEvent.type(screen.getByLabelText('Units'), '4')
    await userEvent.type(screen.getByLabelText('Price per unit'), '120')
    // USD instrument: the sale needs a rate, either typed or the ECB prefill
    await userEvent.type(screen.getByLabelText(/Exchange rate/), '1')
    const table = await screen.findByRole('table', { name: 'Lots used by this sale' })
    expect(table).toHaveTextContent('2025-01-10')
    expect(screen.getByText(/6 units with a cost basis of/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Save transaction' }))
    await waitFor(() => expect(onDone).toHaveBeenCalled())
    const post = calls.find((c) => c.method === 'POST' && c.path === '/api/v1/transactions')
    expect(post?.body).toMatchObject({
      type: 'sell',
      quantity: '4',
      account_id: 1,
      instrument_id: 1,
    })
  })

  it('shows the server explanation of an oversell next to the preview', async () => {
    mockApi({
      ...BASE,
      'POST /api/v1/transactions/preview-sell': problem(
        422,
        'Not enough units',
        'You hold 6 units on 2025-03-03; this sale needs 10.',
      ),
    })
    renderAt(<TransactionForm onDone={vi.fn()} initial={{ type: 'sell' }} />)
    await screen.findByRole('option', { name: /Acme Corp/ })
    await userEvent.selectOptions(screen.getByLabelText('Instrument'), '1')
    await userEvent.type(screen.getByLabelText('Units'), '10')
    await userEvent.type(screen.getByLabelText('Price per unit'), '120')
    await userEvent.type(screen.getByLabelText(/Exchange rate/), '1')
    expect(await screen.findByText(/You hold 6 units/)).toBeInTheDocument()
  })

  it('prefills the ECB rate and says which day it is from', async () => {
    mockApi({
      ...BASE,
      '/api/v1/transactions/fx-prefill': {
        currency: 'USD',
        date: '2025-03-03',
        rate_per_eur: '1.0950',
        fx_rate_to_eur: '0.9132420091',
        rate_date: '2025-02-28',
      },
    })
    renderAt(<TransactionForm onDone={vi.fn()} />)
    await screen.findByRole('option', { name: /Acme Corp/ })
    await userEvent.selectOptions(screen.getByLabelText('Instrument'), '1')
    expect(await screen.findByText(/ECB rate of 2025-02-28/)).toBeInTheDocument()
    expect(screen.getByLabelText(/Exchange rate/)).toHaveAttribute('placeholder', '1.095')
  })
})
