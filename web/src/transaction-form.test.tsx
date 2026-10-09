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

// FR-TX-14: a calculated amount while typing, and every stored parameter can be edited
const STORED = {
  id: 5,
  account_id: 1,
  account_name: 'Degiro',
  instrument_id: 1,
  instrument_name: 'Acme Corp',
  ticker: 'ACME',
  type: 'buy',
  status: 'posted',
  trade_date: '2025-01-10',
  settle_date: null,
  quantity: '10',
  price: '100',
  currency: 'USD',
  fx_rate_to_eur: '0.9',
  fees: '1.5',
  fees_currency: 'EUR',
  fees_fx_rate_to_eur: '1',
  taxes: '0',
  taxes_currency: 'EUR',
  taxes_fx_rate_to_eur: '1',
  net_amount_eur: '-901.5',
  ratio: null,
  note: null,
  source: 'csv',
  external_ref: 'ORDER-1',
  import_batch_id: 3,
}
const AMOUNT = {
  currency: 'USD',
  fx_rate_to_eur: '0.9',
  gross_eur: '900',
  fees_eur: '1.5',
  taxes_eur: '0',
  net_amount_eur: '-901.5',
}

describe('the calculated amount (FR-TX-14)', () => {
  it('shows what the server calculates as units and price are typed', async () => {
    const { calls } = mockApi({
      ...BASE,
      'POST /api/v1/transactions/preview-amount': AMOUNT,
      '/api/v1/transactions/fx-prefill': {
        currency: 'USD',
        date: '2025-01-10',
        rate_per_eur: '1.1111',
        rate_date: '2025-01-10',
        fx_rate_to_eur: '0.9',
      },
    })
    renderAt(<TransactionForm onDone={vi.fn()} initial={{ type: 'buy' }} />)
    expect(screen.getByText(/Fill in the units and price to see the amount/)).toBeInTheDocument()
    await screen.findByRole('option', { name: /Acme Corp/ })
    await userEvent.selectOptions(screen.getByLabelText('Instrument'), '1')
    await userEvent.type(screen.getByLabelText('Units'), '10')
    await userEvent.type(screen.getByLabelText('Price per unit'), '100')
    const table = await screen.findByRole('table', {
      name: 'How the amount in euros is calculated',
    })
    expect(table).toHaveTextContent('Units × price (in €)€900.00')
    expect(table).toHaveTextContent('Fees (€)€1.50')
    expect(table).toHaveTextContent('Total paid (€)€901.50') // a buy: shown as what you paid
    const call = calls.filter((c) => c.path === '/api/v1/transactions/preview-amount').at(-1)
    expect(call?.body).toMatchObject({ type: 'buy', quantity: '10', price: '100' })
  })

  it('calls a sale proceeds, and shows nothing for types without a calculated amount', async () => {
    mockApi({
      ...BASE,
      'POST /api/v1/transactions/preview-amount': { ...AMOUNT, net_amount_eur: '898' },
      'POST /api/v1/transactions/preview-sell': PREVIEW,
    })
    renderAt(<TransactionForm onDone={vi.fn()} initial={{ type: 'sell' }} />)
    await screen.findByRole('option', { name: /Acme Corp/ })
    await userEvent.selectOptions(screen.getByLabelText('Instrument'), '1')
    await userEvent.type(screen.getByLabelText('Units'), '10')
    await userEvent.type(screen.getByLabelText('Price per unit'), '100')
    await userEvent.type(screen.getByLabelText(/Exchange rate/), '1.1111')
    expect(await screen.findByText('Total received (€)')).toBeInTheDocument()
    await userEvent.selectOptions(screen.getByLabelText('Type'), 'dividend')
    expect(screen.queryByText('Calculated amount')).not.toBeInTheDocument()
  })
})

describe('editing a stored transaction (FR-TX-14)', () => {
  const editRoutes = {
    ...BASE,
    '/api/v1/accounts': [ACCOUNT, { ...ACCOUNT, id: 2, name: 'Second' }],
    'POST /api/v1/transactions/preview-amount': AMOUNT,
    'PATCH /api/v1/transactions/5': STORED,
  }

  it('lets the type and the account be changed, which were locked before', async () => {
    mockApi(editRoutes)
    renderAt(<TransactionForm onDone={vi.fn()} editing={STORED as never} />)
    await screen.findByRole('option', { name: 'Second' })
    expect(screen.getByLabelText('Type')).toBeEnabled()
    expect(screen.getByLabelText('Account')).toBeEnabled()
    expect(screen.queryByText(/cannot be changed/)).not.toBeInTheDocument()
  })

  it('shows the stored price and units exactly, though lists show two decimals (ADR 0052)', async () => {
    mockApi(editRoutes)
    renderAt(
      <TransactionForm
        onDone={vi.fn()}
        editing={{ ...STORED, quantity: '1.23456', price: '98.5432' } as never}
      />,
    )
    await screen.findByRole('option', { name: 'Second' })
    // a field you type into holds the exact value, so saving never rounds it
    expect(screen.getByLabelText(/Price per unit/)).toHaveValue('98.5432')
    expect(screen.getByLabelText('Units')).toHaveValue('1.23456')
  })

  it('sends only what changed when the type stays', async () => {
    const { calls } = mockApi(editRoutes)
    const onDone = vi.fn()
    renderAt(<TransactionForm onDone={onDone} editing={STORED as never} />)
    await screen.findByRole('option', { name: 'Second' })
    await userEvent.clear(screen.getByLabelText('Units'))
    await userEvent.type(screen.getByLabelText('Units'), '12')
    await userEvent.clear(screen.getByLabelText('Price per unit'))
    await userEvent.type(screen.getByLabelText('Price per unit'), '101')
    await userEvent.clear(screen.getByLabelText('Trade date'))
    await userEvent.type(screen.getByLabelText('Trade date'), '2025-01-09')
    await userEvent.click(screen.getByRole('button', { name: 'Save transaction' }))
    await waitFor(() => expect(onDone).toHaveBeenCalled())
    const patch = calls.find((c) => c.method === 'PATCH')
    expect(patch?.path).toBe('/api/v1/transactions/5')
    expect(patch?.body).toEqual({ quantity: '12', price: '101', trade_date: '2025-01-09' })
  })

  it('sends the whole transaction when the type changes, and the account when it moves', async () => {
    const { calls } = mockApi(editRoutes)
    const onDone = vi.fn()
    renderAt(<TransactionForm onDone={onDone} editing={STORED as never} />)
    await screen.findByRole('option', { name: 'Second' })
    await userEvent.selectOptions(screen.getByLabelText('Type'), 'sell')
    await userEvent.selectOptions(screen.getByLabelText('Account'), '2')
    await userEvent.click(screen.getByRole('button', { name: 'Save transaction' }))
    await waitFor(() => expect(onDone).toHaveBeenCalled())
    const patch = calls.find((c) => c.method === 'PATCH')
    expect(patch?.body).toMatchObject({
      type: 'sell',
      account_id: 2,
      instrument_id: 1,
      quantity: '10',
      price: '100',
      trade_date: '2025-01-10',
    })
  })

  it('shows the amount of the stored trade at once, and recalculates it on a change', async () => {
    mockApi({
      ...editRoutes,
      'POST /api/v1/transactions/preview-amount': async (request: Request) => {
        const body = (await request.clone().json()) as { quantity: string }
        const gross = Number(body.quantity) * 90
        return { ...AMOUNT, gross_eur: String(gross), net_amount_eur: String(-(gross + 1.5)) }
      },
    })
    renderAt(<TransactionForm onDone={vi.fn()} editing={STORED as never} />)
    const amountTable = () =>
      screen.getByRole('table', { name: 'How the amount in euros is calculated' })
    await waitFor(() => expect(amountTable()).toHaveTextContent('Total paid (€)€901.50'))
    await userEvent.clear(screen.getByLabelText('Units'))
    // with the units gone there is nothing to calculate, and no old figure is left standing
    expect(screen.getByText(/Fill in the units and price to see the amount/)).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Units'), '20')
    await waitFor(() => expect(amountTable()).toHaveTextContent('Total paid (€)€1,801.50'))
  })
})
