import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ConfigPanel } from './dashboards/ConfigPanel'
import { PriceHistoryWidget } from './dashboards/widgets/History'
import { GENERAL_US, mockApi, renderAt } from './test-utils'

interface Drawn {
  kind: string
  pane: number
  data: Record<string, unknown>[]
}
const chart = vi.hoisted(() => ({ series: [] as Drawn[], options: {} as Record<string, unknown> }))

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
      addSeries: (kind: string, _options: unknown, pane = 0) => {
        const entry: Drawn = { kind, pane, data: [] }
        chart.series.push(entry)
        return {
          setData: (data: Record<string, unknown>[]) => {
            entry.data = data
          },
        }
      },
      panes: () => [{ setStretchFactor: vi.fn() }],
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
  localStorage.clear()
  mockApi({ '/api/v1/settings/general': GENERAL_US })
})
afterEach(() => vi.unstubAllGlobals())

const series = (id: number, name: string, currency: string, points: [string, string][]) => ({
  instrument_id: id,
  name,
  currency,
  points: points.map(([date, value]) => ({ date, value })),
  last: points.at(-1)?.[1] ?? null,
  change_ratio: '0.0123',
})
const days = {
  intraday: false,
  start: '2024-01-08',
  end: '2024-01-15',
  series: [
    series(4, 'World fund', 'EUR', [
      ['2024-01-09', '100'],
      ['2024-01-10', '101.5'],
    ]),
    series(5, 'US stock', 'USD', [
      ['2024-01-09', '50'],
      ['2024-01-10', '52'],
    ]),
  ],
  notes: [],
}
const show = (data: object) => renderAt(<PriceHistoryWidget data={data} config={{}} filters={{}} />)

describe('the price history widget', () => {
  it('draws each instrument in a pane of its own, with the closing price of each day', () => {
    show(days)
    expect(chart.series.map((s) => [s.kind, s.pane])).toEqual([
      ['line', 0],
      ['line', 1],
    ])
    expect(chart.series[0].data).toEqual([
      { time: '2024-01-09', value: 100 },
      { time: '2024-01-10', value: 101.5 },
    ])
  })

  it('says what each instrument is at, as a link to its position, with the change', () => {
    show(days)
    const list = screen.getByRole('list', { name: 'Price history' })
    expect(within(list).getByRole('link', { name: 'World fund' })).toHaveAttribute(
      'href',
      '/holdings/4',
    )
    expect(list).toHaveTextContent(/101[.,]50 EUR/)
    expect(list).toHaveTextContent(/52[.,]00 USD/)
    expect(list).toHaveTextContent(/1[.,]23\s?%/)
  })

  it('draws one day on the clock, stretched from the open to the close of trading', () => {
    show({
      intraday: true,
      day: '2024-01-16',
      today: false,
      session: { start: '2024-01-16T09:00:00', end: '2024-01-16T17:30:00' },
      series: [
        series(4, 'World fund', 'EUR', [
          ['2024-01-16T09:00:00', '109'],
          ['2024-01-16T10:15:00', '110.5'],
        ]),
      ],
      notes: [],
    })
    const clock = (iso: string) => Date.parse(`${iso}Z`) / 1000
    expect(chart.series[0].data.map((d) => d.time)).toEqual([
      clock('2024-01-16T09:00:00'),
      clock('2024-01-16T10:15:00'),
      clock('2024-01-16T17:30:00'), // whitespace: the close, which the curve has not reached
    ])
    expect(chart.series[0].data.at(-1)).toEqual({ time: clock('2024-01-16T17:30:00') })
    expect(chart.options.timeScale).toMatchObject({ timeVisible: true })
    expect(screen.getByText(/Trading day 2024-01-16/)).toBeVisible()
    expect(screen.getByText(/Not today: the latest day with refresh prices/)).toBeVisible()
  })

  it('reads as a table with a column for each instrument', async () => {
    show(days)
    await userEvent.click(screen.getByRole('button', { name: 'Show data as a table' }))
    const table = screen.getByRole('table')
    expect(
      within(table)
        .getAllByRole('columnheader')
        .map((h) => h.textContent),
    ).toEqual(['Date', 'World fund (EUR)', 'US stock (USD)'])
    expect(within(table).getAllByRole('row')[1]).toHaveTextContent('2024-01-10')
  })

  it('says what to do when nothing is chosen', () => {
    show({ empty: true, reason: 'Choose at least one instrument in the settings of this widget.' })
    expect(screen.getByText(/Choose at least one instrument/)).toBeVisible()
  })

  it('shows the notes under the chart', () => {
    show({ ...days, notes: ['No prices are stored for Old fund in this period.'] })
    expect(screen.getByText('No prices are stored for Old fund in this period.')).toBeVisible()
  })
})

describe('choosing the instruments in the settings', () => {
  it('adds and removes instruments', async () => {
    mockApi({
      '/api/v1/settings/general': GENERAL_US,
      '/api/v1/instruments': [
        { id: 4, name: 'World fund', status: 'active', listings: [] },
        { id: 5, name: 'US stock', status: 'active', listings: [] },
      ],
      'POST /api/v1/widgets/data': { results: { preview: { data: { empty: true, reason: 'x' } } } },
    })
    const onSave = vi.fn()
    renderAt(
      <ConfigPanel
        widget={{ id: 9, type: 'price_history', grid: {}, config: { instrument_ids: [4] } }}
        breakpoint="lg"
        box={undefined}
        filters={{}}
        saving={false}
        onClose={() => undefined}
        onSave={onSave}
      />,
    )
    const group = await screen.findByRole('group', { name: 'Instruments' })
    expect(await within(group).findByText('World fund')).toBeVisible()
    const add = await within(group).findByRole('combobox', { name: 'Add an instrument' })
    await userEvent.selectOptions(add, '5')
    expect(within(group).getAllByRole('listitem')).toHaveLength(2)
    await userEvent.click(within(group).getByRole('button', { name: 'Remove World fund' }))
    // World fund is gone from the list and offered again to add
    expect(within(group).getAllByRole('listitem')).toHaveLength(1)
    expect(within(group).getByRole('listitem')).toHaveTextContent('US stock')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(onSave.mock.calls[0][0]).toMatchObject({ instrument_ids: [5] })
  })
})
