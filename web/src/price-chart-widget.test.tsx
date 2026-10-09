import { screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ConfigPanel } from './dashboards/ConfigPanel'
import { PriceChartWidget } from './dashboards/widgets/History'
import { GENERAL_US, mockApi, renderAt } from './test-utils'

interface Drawn {
  kind: string
  options: Record<string, unknown>
  pane: number
  data: Record<string, unknown>[]
}
const chart = vi.hoisted(() => ({
  series: [] as Drawn[],
  options: {} as Record<string, unknown>,
  stretched: [] as number[],
}))

vi.mock('lightweight-charts', () => ({
  AreaSeries: 'area',
  CandlestickSeries: 'candles',
  ColorType: { Solid: 'solid' },
  HistogramSeries: 'histogram',
  LineSeries: 'line',
  PriceScaleMode: { Normal: 0, Logarithmic: 1 },
  createChart: (_el: unknown, options: Record<string, unknown>) => {
    chart.options = options
    return {
      addSeries: (kind: string, seriesOptions: Record<string, unknown>, pane = 0) => {
        const entry: Drawn = { kind, options: seriesOptions, pane, data: [] }
        chart.series.push(entry)
        return {
          setData: (data: Record<string, unknown>[]) => {
            entry.data = data
          },
        }
      },
      panes: () => [{ setStretchFactor: (n: number) => chart.stretched.push(n) }],
      timeScale: () => ({ fitContent: vi.fn() }),
      subscribeCrosshairMove: vi.fn(),
      subscribeClick: vi.fn(),
      remove: vi.fn(),
    }
  },
  createSeriesMarkers: vi.fn(),
}))

beforeEach(() => {
  chart.series = []
  chart.stretched = []
})
afterEach(() => vi.unstubAllGlobals())

const daily = {
  instrument_id: 4,
  name: 'World fund',
  currency: 'EUR',
  chart: 'line' as const,
  points: [
    { date: '2024-01-03', open: null, high: null, low: null, close: '110', volume: null },
    { date: '2024-01-04', open: null, high: null, low: null, close: '99', volume: null },
  ],
  trades: [],
  show_price: true,
}
const changes = [
  { date: '2024-01-03', value: '10' },
  { date: '2024-01-04', value: '-10' },
]
const since = [
  { date: '2024-01-03', value: '10' },
  { date: '2024-01-04', value: '-1' },
]
const show = (data: object, overlays: string[] = ['price']) =>
  renderAt(<PriceChartWidget data={{ ...daily, ...data }} config={{ overlays }} filters={{}} />)

describe('the price chart widget: price changes (FR-DB-03)', () => {
  it('draws the price alone as before', () => {
    mockApi({ '/api/v1/settings/general': GENERAL_US })
    show({})
    expect(chart.series.map((s) => [s.kind, s.pane])).toEqual([['line', 0]])
    expect(chart.series[0].data).toEqual([
      { time: '2024-01-03', value: 110 },
      { time: '2024-01-04', value: 99 },
    ])
    expect(chart.stretched).toEqual([]) // one pane
  })

  it('puts each change view in a pane of its own under the price', () => {
    mockApi({ '/api/v1/settings/general': GENERAL_US })
    show({ changes, since_start: since }, ['price', 'changes', 'since_start'])
    expect(chart.series.map((s) => [s.kind, s.pane])).toEqual([
      ['line', 0],
      ['histogram', 1],
      ['line', 2],
    ])
    const bars = chart.series[1]
    expect(bars.data.map((d) => d.value)).toEqual([10, -10])
    expect(bars.data.every((d) => typeof d.color === 'string')).toBe(true) // green or red by sign
    expect(chart.stretched).toEqual([3]) // the price keeps the biggest pane
  })

  it('draws just the changes when the price is left out, in the first pane', () => {
    mockApi({ '/api/v1/settings/general': GENERAL_US })
    show({ show_price: false, changes }, ['changes'])
    expect(chart.series.map((s) => [s.kind, s.pane])).toEqual([['histogram', 0]])
    expect(screen.queryByText('99')).toBeNull()
  })

  it('reads the changes as a table, with the price when it is shown', async () => {
    mockApi({ '/api/v1/settings/general': GENERAL_US })
    show({ changes, since_start: since }, ['price', 'changes', 'since_start'])
    await (
      await import('@testing-library/user-event')
    ).default.click(screen.getByRole('button', { name: 'Show data as a table' }))
    const table = screen.getByRole('table')
    expect(
      within(table)
        .getAllByRole('columnheader')
        .map((h) => h.textContent),
    ).toEqual(['Date', 'Close', 'Change per day', 'Change since the start'])
    const rows = within(table).getAllByRole('row')
    expect(rows[1]).toHaveTextContent('2024-01-04')
    expect(rows[1]).toHaveTextContent('-10.00%')
    expect(rows[1]).toHaveTextContent('-1.00%')
  })

  it('draws one day from the refresh prices, on the clock of the exchange', () => {
    mockApi({ '/api/v1/settings/general': GENERAL_US })
    show(
      {
        intraday: true,
        session_date: '2024-01-12',
        previous_close: '100',
        points: [
          {
            date: '2024-01-12T09:00:00',
            open: null,
            high: null,
            low: null,
            close: '109',
            volume: null,
          },
          {
            date: '2024-01-12T09:15:00',
            open: null,
            high: null,
            low: null,
            close: '110.5',
            volume: null,
          },
        ],
        changes: [
          { date: '2024-01-12T09:00:00', value: '9' },
          { date: '2024-01-12T09:15:00', value: '1.38' },
        ],
      },
      ['price', 'changes'],
    )
    const price = chart.series[0]
    expect(price.data.map((d) => d.time)).toEqual([
      Date.parse('2024-01-12T09:00:00Z') / 1000,
      Date.parse('2024-01-12T09:15:00Z') / 1000,
    ])
    expect(chart.options.timeScale).toMatchObject({ timeVisible: true })
    expect(screen.getByText(/Session of 2024-01-12 · previous close 100[.,]00/)).toBeVisible()
  })

  it('says what is missing when a day has no refresh prices', () => {
    mockApi({ '/api/v1/settings/general': GENERAL_US })
    show({ empty: true, reason: 'No refresh prices are stored for this instrument yet.' })
    expect(screen.getByText(/No refresh prices are stored/)).toBeVisible()
  })
})

describe('the settings of the price chart', () => {
  it('offers the price and both change views in Show, and a preview with a height of its own', async () => {
    mockApi({
      '/api/v1/settings/general': GENERAL_US,
      'POST /api/v1/widgets/data': { results: { preview: { data: { ...daily, changes } } } },
    })
    renderAt(
      <ConfigPanel
        widget={{
          id: 5,
          type: 'price_chart',
          grid: {},
          config: { instrument_id: 4, overlays: ['price', 'trades'] },
        }}
        breakpoint="lg"
        box={undefined}
        filters={{}}
        saving={false}
        onClose={() => undefined}
        onSave={() => undefined}
      />,
    )
    const show = await screen.findByRole('group', { name: 'Show' })
    for (const name of [
      'The price',
      'Your buys and sales',
      '50-day average',
      '200-day average',
      'Volume',
      'Price changes (daily; per refresh for 1 day)',
      'Change since the start',
    ]) {
      expect(within(show).getByRole('checkbox', { name })).toBeInTheDocument()
    }
    expect(within(show).getByRole('checkbox', { name: 'The price' })).toBeChecked()
    expect(within(show).getByRole('checkbox', { name: 'Volume' })).not.toBeChecked()
    // the timeframe is chosen here too, from "follow the dashboard" to MAX
    const period = screen.getByLabelText('Period')
    expect(within(period).getByRole('option', { name: 'Follow the dashboard' })).toBeVisible()
    expect(within(period).getByRole('option', { name: /1 day|Day/i })).toBeVisible()
    // the preview chart sits in a box of fixed height, so it cannot grow without end
    expect(screen.getByTestId('preview-body').className).toContain('h-80')
  })
})
