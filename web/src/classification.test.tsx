import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { InstrumentsTab } from './components/InstrumentsTab'
import { SleevesTab } from './components/SleevesTab'
import { parseProposal, WhatIf } from './pages/WhatIf'
import { Watchlist } from './pages/Watchlist'
import { GENERAL_US, mockApi, renderAt } from './test-utils'

vi.mock('lightweight-charts', () => {
  const series = () => ({ setData: vi.fn() })
  return {
    ColorType: { Solid: 'solid' },
    LineSeries: 'line',
    createChart: () => ({
      addSeries: series,
      timeScale: () => ({ fitContent: vi.fn() }),
      remove: vi.fn(),
    }),
    createSeriesMarkers: vi.fn(),
  }
})

afterEach(() => vi.unstubAllGlobals())

const sleeve = (over: Record<string, unknown> = {}) => ({
  id: 1,
  name: 'Core',
  target_pct: '60',
  band_pct: '5',
  sort_order: 1,
  instrument_count: 2,
  ...over,
})

const instrument = (over: Record<string, unknown> = {}) => ({
  id: 1,
  name: 'Demo World ETF',
  isin: 'IE00DEMO0001',
  asset_class: 'ETF',
  status: 'active',
  manual: false,
  listings: [{ ticker: 'DWLD', mic: 'XETR', currency: 'EUR' }],
  last_close: null,
  stale: false,
  tags: [],
  issuer: null,
  ter_pct: null,
  distribution: null,
  region: null,
  sector: null,
  sleeve_id: null,
  is_benchmark: false,
  ...over,
})

describe('sleeves (FR-INS-04)', () => {
  it('lists sleeves with optional targets and says so when there are none', async () => {
    mockApi({
      '/api/v1/settings/general': GENERAL_US,
      '/api/v1/sleeves': [
        sleeve(),
        sleeve({ id: 2, name: 'Gold', target_pct: null, band_pct: null }),
      ],
    })
    renderAt(<SleevesTab />)
    const table = await screen.findByRole('table', { name: 'Your sleeves' })
    const rowOf = (name: string) => within(table).getByText(name).closest('tr') as HTMLElement
    expect(rowOf('Core')).toHaveTextContent(/60 %.*± 5 pp/)
    // a sleeve without a target shows dashes, so no drift is implied (owner decision Q3)
    expect(rowOf('Gold')).toHaveTextContent(/–.*–/)
  })

  it('shows an empty state with the next step', async () => {
    mockApi({ '/api/v1/sleeves': [] })
    renderAt(<SleevesTab />)
    expect(await screen.findByText('No sleeves yet')).toBeInTheDocument()
  })

  it('creates a sleeve with an empty target as null', async () => {
    const { calls } = mockApi({
      '/api/v1/sleeves': (request: Request) => (request.method === 'POST' ? sleeve() : []),
    })
    renderAt(<SleevesTab />)
    await userEvent.click(await screen.findByRole('button', { name: 'Add sleeve' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText('Name'), 'Satellite')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save sleeve' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({
      name: 'Satellite',
      target_pct: null,
      band_pct: null,
    })
  })

  it('puts instruments in a sleeve from its own form, moving one from another sleeve', async () => {
    const { calls } = mockApi({
      '/api/v1/sleeves': (request: Request) =>
        request.method === 'POST'
          ? sleeve({ id: 7, name: 'Satellite', target_pct: null, band_pct: null })
          : [sleeve({ id: 3, name: 'Core' })],
      '/api/v1/instruments': [
        instrument({ id: 5, name: 'Demo Gold ETC', sleeve_id: null }),
        instrument({ id: 6, name: 'Demo Bond ETF', sleeve_id: 3 }),
      ],
      'PATCH /api/v1/instruments/5': {},
      'PATCH /api/v1/instruments/6': {},
    })
    renderAt(<SleevesTab />)
    await userEvent.click(await screen.findByRole('button', { name: 'Add sleeve' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText('Name'), 'Satellite')
    await userEvent.click(await within(dialog).findByLabelText('Demo Gold ETC'))
    await userEvent.click(within(dialog).getByLabelText('Demo Bond ETF'))
    expect(within(dialog).getByText('moves from Core')).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save sleeve' }))
    await waitFor(() => expect(calls.filter((c) => c.method === 'PATCH').length).toBe(2))
    const bodyOf = (id: number) =>
      calls.find((c) => c.method === 'PATCH' && c.path === `/api/v1/instruments/${id}`)?.body
    expect(bodyOf(5)).toEqual({ sleeve_id: 7 })
    expect(bodyOf(6)).toEqual({ sleeve_id: 7 })
  })

  it('needs a name', async () => {
    const { calls } = mockApi({ '/api/v1/sleeves': [] })
    renderAt(<SleevesTab />)
    await userEvent.click(await screen.findByRole('button', { name: 'Add sleeve' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save sleeve' }))
    expect(await within(dialog).findByText('This is required.')).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
  })

  it('warns when targets add up to more than 100 percent', async () => {
    mockApi({
      '/api/v1/sleeves': [
        sleeve({ target_pct: '70' }),
        sleeve({ id: 2, name: 'B', target_pct: '50' }),
      ],
    })
    renderAt(<SleevesTab />)
    expect(await screen.findByRole('alert')).toHaveTextContent('120%')
  })

  it('saves the new order when a sleeve is moved up', async () => {
    const { calls } = mockApi({
      '/api/v1/sleeves': [sleeve(), sleeve({ id: 2, name: 'Gold' })],
      'PUT /api/v1/sleeves/order': [],
    })
    renderAt(<SleevesTab />)
    await userEvent.click(await screen.findByRole('button', { name: 'Move Gold up' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PUT')).toBe(true))
    expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({ ids: [2, 1] })
  })
})

describe('classifying an instrument (FR-INS-04, FR-MD-12)', () => {
  it('sets region, sector, sleeve and the benchmark flag', async () => {
    const { calls } = mockApi({
      '/api/v1/settings/general': GENERAL_US,
      '/api/v1/instruments': [instrument()],
      '/api/v1/sleeves': [sleeve()],
      'PATCH /api/v1/instruments/1': instrument(),
    })
    renderAt(<InstrumentsTab onAdd={() => undefined} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Edit' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText('Region'), 'Global')
    await userEvent.type(within(dialog).getByLabelText('Sector'), 'Broad market')
    await within(dialog).findByRole('option', { name: 'Core' })
    await userEvent.selectOptions(within(dialog).getByLabelText('Sleeve'), 'Core')
    await userEvent.click(within(dialog).getByLabelText('Use as a benchmark'))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true))
    expect(calls.find((c) => c.method === 'PATCH')?.body).toMatchObject({
      region: 'Global',
      sector: 'Broad market',
      sleeve_id: 1,
      is_benchmark: true,
    })
  })
})

describe('the issuer page of a fund', () => {
  it('is saved from the edit window, trimmed, and cleared when emptied', async () => {
    const { calls } = mockApi({
      '/api/v1/settings/general': GENERAL_US,
      '/api/v1/instruments': [{ ...instrument(), product_url: 'https://old.example/page' }],
      '/api/v1/sleeves': [sleeve()],
      'PATCH /api/v1/instruments/1': instrument(),
    })
    renderAt(<InstrumentsTab onAdd={() => undefined} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Edit' }))
    const dialog = await screen.findByRole('dialog')
    const field = within(dialog).getByLabelText("Issuer's page for this fund (web address)")
    expect(field).toHaveValue('https://old.example/page')
    await userEvent.clear(field)
    await userEvent.type(field, '  https://www.ishares.com/nl/producten/253743  ')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true))
    expect(calls.find((c) => c.method === 'PATCH')?.body).toMatchObject({
      product_url: 'https://www.ishares.com/nl/producten/253743',
    })
  })
})

describe('watchlist (FR-INS-05)', () => {
  const list = (items: unknown[]) => [{ id: 1, name: 'Watchlist', items }]
  const item = (over: Record<string, unknown> = {}) => ({
    id: 10,
    instrument_id: 5,
    name: 'Demo Gold ETC',
    isin: null,
    ticker: 'DGLD',
    currency: 'EUR',
    note: 'wait for a dip',
    close: '110',
    close_date: '2026-10-02',
    previous_close: '100',
    stale: false,
    fetching: false,
    ...over,
  })

  it('says prices are being fetched for a new item and can ask for them again', async () => {
    const { calls } = mockApi({
      '/api/v1/settings/general': GENERAL_US,
      '/api/v1/watchlists': list([item({ close: null, previous_close: null, fetching: true })]),
      'POST /api/v1/watchlists/1/refresh': list([item()])[0],
      '/api/v1/instruments': [],
    })
    renderAt(<Watchlist />)
    expect(await screen.findByText('Fetching prices...')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent(/Fetching prices and history/)
    expect(screen.getByRole('button', { name: 'Fetch prices now' })).toBeDisabled()
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
  })

  it('shows the last close, the day change and the note of a watched instrument', async () => {
    mockApi({
      '/api/v1/settings/general': GENERAL_US,
      '/api/v1/watchlists': list([item()]),
      '/api/v1/instruments': [instrument({ id: 5, name: 'Demo Gold ETC' })],
    })
    renderAt(<Watchlist />)
    const row = await screen.findByRole('row', { name: /Demo Gold ETC/ })
    expect(within(row).getByText(/110[.,]00 EUR/)).toBeInTheDocument()
    expect(within(row).getByText(/10[.,]00%/)).toBeInTheDocument()
    expect(within(row).getByLabelText('Note for Demo Gold ETC')).toHaveValue('wait for a dip')
  })

  it('adds an instrument you do not hold, offering only those not already watched', async () => {
    const { calls } = mockApi({
      '/api/v1/settings/general': GENERAL_US,
      '/api/v1/watchlists': list([item()]),
      'POST /api/v1/watchlists/1/items': list([item()])[0],
      '/api/v1/instruments': [
        instrument({ id: 5, name: 'Demo Gold ETC' }),
        instrument({ id: 6, name: 'Demo Bond ETF' }),
      ],
    })
    renderAt(<Watchlist />)
    const picker = await screen.findByLabelText('Instrument to watch')
    await within(picker).findByRole('option', { name: 'Demo Bond ETF' })
    expect(within(picker).queryByRole('option', { name: 'Demo Gold ETC' })).not.toBeInTheDocument()
    await userEvent.selectOptions(picker, 'Demo Bond ETF')
    await userEvent.click(screen.getByRole('button', { name: 'Add to watchlist' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ instrument_id: 6 })
  })

  it('saves a note when the field loses focus', async () => {
    const { calls } = mockApi({
      '/api/v1/settings/general': GENERAL_US,
      '/api/v1/watchlists': list([item({ note: null })]),
      'PATCH /api/v1/watchlists/1/items/10': list([item()])[0],
      '/api/v1/instruments': [],
    })
    renderAt(<Watchlist />)
    const field = await screen.findByLabelText('Note for Demo Gold ETC')
    await userEvent.type(field, 'buy under 105')
    await userEvent.tab()
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true))
    expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ note: 'buy under 105' })
  })

  it('draws the price chart on request and says so when there are no prices', async () => {
    mockApi({
      '/api/v1/settings/general': GENERAL_US,
      '/api/v1/watchlists': list([item()]),
      '/api/v1/instruments': [],
      '/api/v1/instruments/5/prices': [],
    })
    renderAt(<Watchlist />)
    await userEvent.click(await screen.findByRole('button', { name: 'Chart' }))
    expect(await screen.findByText(/no prices/i)).toBeInTheDocument()
  })

  it('has an empty state that says what to do', async () => {
    mockApi({
      '/api/v1/settings/general': GENERAL_US,
      '/api/v1/watchlists': list([]),
      '/api/v1/instruments': [],
    })
    renderAt(<Watchlist />)
    expect(await screen.findByText('Watchlist is empty')).toBeInTheDocument()
  })
})

describe('what-if (FR-PF-09)', () => {
  const sliceOf = (key: string, weight: string, over: Record<string, unknown> = {}) => ({
    key,
    value_eur: '0',
    weight,
    target: null,
    drift_pp: null,
    drift_relative: null,
    outside_band: null,
    ...over,
  })
  const allocation = (slices: unknown[]) => ({
    group_by: 'asset_class',
    as_of: '2026-10-02',
    total_eur: '1000',
    unvalued_positions: 0,
    slices,
  })
  const result = {
    as_of: '2026-10-02',
    cash_needed_eur: '250',
    before: allocation([sliceOf('ETF', '1')]),
    after: allocation([sliceOf('ETF', '0.8'), sliceOf('BOND', '0.2')]),
    positions: [
      {
        instrument_id: 6,
        name: 'Demo Bond ETF',
        quantity_before: '0',
        quantity_after: '5',
        value_before_eur: '0',
        value_after_eur: '250',
      },
    ],
  }
  const routes = (extra: Record<string, unknown> = {}) => ({
    '/api/v1/settings/general': GENERAL_US,
    '/api/v1/accounts': [],
    '/api/v1/instruments': [instrument({ id: 6, name: 'Demo Bond ETF' })],
    ...extra,
  })

  it('shows the cash needed and the allocation before and after, and writes nothing', async () => {
    const { calls } = mockApi(routes({ 'POST /api/v1/portfolio/simulate': result }))
    renderAt(<WhatIf />)
    await screen.findByRole('option', { name: 'Demo Bond ETF' })
    await userEvent.selectOptions(screen.getByLabelText('Instrument'), 'Demo Bond ETF')
    await userEvent.type(screen.getByLabelText('Units'), '5')
    await userEvent.click(screen.getByRole('button', { name: 'Show the result' }))
    expect(await screen.findByRole('status')).toHaveTextContent('You would need')
    expect(screen.getByRole('status')).toHaveTextContent('250.00')
    const table = screen.getByRole('table', { name: /Allocation by/ })
    expect(within(table).getByRole('row', { name: /BOND.*0\.0%.*20\.0%/ })).toBeInTheDocument()
    const sent = calls.find((c) => c.path === '/api/v1/portfolio/simulate')
    expect(sent?.body).toMatchObject({
      group_by: 'asset_class',
      trades: [{ instrument_id: 6, side: 'buy', quantity: '5', fees_eur: '0' }],
    })
    // the only write-shaped call is the simulation itself, which saves nothing
    expect(
      calls.filter((c) => c.method !== 'GET' && c.path !== '/api/v1/portfolio/simulate'),
    ).toEqual([])
  })

  it('names the rows that are not filled in and sends nothing', async () => {
    const { calls } = mockApi(routes())
    renderAt(<WhatIf />)
    await userEvent.click(await screen.findByRole('button', { name: 'Show the result' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Trade 1: choose an instrument.')
    expect(alert).toHaveTextContent('Trade 1: enter the number of units')
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
  })

  it('shows drift against targets when sleeves have them', async () => {
    mockApi(
      routes({
        'POST /api/v1/portfolio/simulate': {
          ...result,
          before: allocation([sliceOf('Core', '1', { target: '0.6', drift_pp: '0.4' })]),
          after: allocation([
            sliceOf('Core', '0.62', { target: '0.6', drift_pp: '0.02', outside_band: false }),
          ]),
        },
      }),
    )
    renderAt(<WhatIf />)
    await screen.findByRole('option', { name: 'Demo Bond ETF' })
    await userEvent.selectOptions(screen.getByLabelText('Instrument'), 'Demo Bond ETF')
    await userEvent.type(screen.getByLabelText('Units'), '1')
    await userEvent.click(screen.getByRole('button', { name: 'Show the result' }))
    const table = await screen.findByRole('table', { name: /Allocation by/ })
    expect(within(table).getByRole('row', { name: /Core.*40\.0 pp.*2\.0 pp/ })).toBeInTheDocument()
  })

  it('prefills the trades from ?proposal=', async () => {
    mockApi(routes())
    const proposal = encodeURIComponent(
      JSON.stringify([{ instrument_id: 6, side: 'sell', quantity: '2' }]),
    )
    renderAt(<WhatIf />, `/what-if?proposal=${proposal}`)
    await screen.findByRole('option', { name: 'Demo Bond ETF' })
    expect(screen.getByLabelText('Units')).toHaveValue('2')
    expect(screen.getByLabelText('Side')).toHaveValue('sell')
  })

  it('ignores a malformed proposal', () => {
    expect(parseProposal('not json')).toEqual([])
    expect(parseProposal('{"a":1}')).toEqual([])
    expect(parseProposal(JSON.stringify([{ instrument_id: 'x' }, 7]))).toEqual([])
    expect(parseProposal(null)).toEqual([])
  })
})
