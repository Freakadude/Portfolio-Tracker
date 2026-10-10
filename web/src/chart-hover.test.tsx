import { screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { PriceChart } from './components/PriceChart'
import { PriceChartWidget } from './dashboards/widgets/History'
import { GENERAL_US, mockApi, renderAt } from './test-utils'

type Move = (param: Record<string, unknown>) => void
const lib = vi.hoisted(() => ({
  options: {} as Record<string, any>, // eslint-disable-line @typescript-eslint/no-explicit-any
  seriesOptions: [] as Record<string, unknown>[],
  apis: [] as object[],
  move: null as Move | null,
}))

vi.mock('lightweight-charts', () => ({
  AreaSeries: 'area',
  CandlestickSeries: 'candles',
  ColorType: { Solid: 'solid' },
  HistogramSeries: 'histogram',
  LineSeries: 'line',
  PriceScaleMode: { Normal: 0, Logarithmic: 1 },
  createChart: (_el: unknown, options: Record<string, unknown>) => {
    lib.options = options
    return {
      addSeries: (_kind: string, seriesOptions: Record<string, unknown>) => {
        const api = { setData: vi.fn() }
        lib.apis.push(api)
        lib.seriesOptions.push(seriesOptions)
        return api
      },
      panes: () => [{ setStretchFactor: vi.fn() }],
      timeScale: () => ({ fitContent: vi.fn(), setVisibleRange: vi.fn() }),
      subscribeCrosshairMove: (handler: Move) => {
        lib.move = handler
      },
      subscribeClick: vi.fn(),
      remove: vi.fn(),
    }
  },
  createSeriesMarkers: vi.fn(),
}))

// the chip is measured to be placed: 80 x 40 in a chart box 400 wide
const WIDTH = 80
const HEIGHT = 40
const HOST = 400
beforeEach(() => {
  lib.seriesOptions = []
  lib.apis = []
  lib.move = null
  Object.defineProperty(HTMLElement.prototype, 'offsetWidth', {
    configurable: true,
    get: () => WIDTH,
  })
  Object.defineProperty(HTMLElement.prototype, 'offsetHeight', {
    configurable: true,
    get: () => HEIGHT,
  })
  Object.defineProperty(HTMLElement.prototype, 'clientWidth', {
    configurable: true,
    get: () => HOST,
  })
})
afterEach(() => {
  vi.unstubAllGlobals()
  // @ts-expect-error the stand-ins are removed again, jsdom has no layout of its own
  delete HTMLElement.prototype.offsetWidth
  // @ts-expect-error see above
  delete HTMLElement.prototype.offsetHeight
  // @ts-expect-error see above
  delete HTMLElement.prototype.clientWidth
})

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

/** The pointer is over `time` at (x, y) of the chart, on the first series. */
const hover = (value: number, x: number, y: number, time = '2024-01-04') =>
  lib.move?.({ time, point: { x, y }, seriesData: new Map([[lib.apis[0], { value }]]) })

const places = () => {
  const chip = screen.getByTestId('cursor-tip')
  return { chip, left: chip.style.left, top: chip.style.top }
}

describe('hovering a dashboard line chart', () => {
  beforeEach(() => {
    mockApi({ '/api/v1/settings/general': GENERAL_US })
    renderAt(<PriceChartWidget data={daily} config={{ overlays: ['price'] }} filters={{}} />)
  })

  it('writes the value above the cursor, not on the price axis', () => {
    expect(lib.options.crosshair.horzLine.labelVisible).toBe(false) // nothing on the right axis
    expect(screen.getByTestId('cursor-tip')).not.toBeVisible()

    hover(99, 200, 120)
    const { chip, left, top } = places()
    expect(chip).toBeVisible()
    expect(chip).toHaveTextContent('2024-01-04')
    expect(chip).toHaveTextContent('99')
    expect(left).toBe('160px') // centred on the cursor: 200 - 80 / 2
    expect(top).toBe('64px') // above it: 120 - 40 high - 16 gap
  })

  it('follows the cursor and goes below it when there is no room above', () => {
    hover(99, 200, 120)
    hover(110, 300, 20)
    const { left, top } = places()
    expect(left).toBe('260px')
    expect(top).toBe('44px') // 20 + 16 + 8, under the cursor
  })

  it('stays inside the chart at both edges', () => {
    hover(99, 3, 120)
    expect(places().left).toBe('4px')
    hover(99, 399, 120)
    expect(places().left).toBe('316px') // 400 - 80 - 4
  })

  it('is hidden when the pointer leaves the chart', () => {
    hover(99, 200, 120)
    lib.move?.({ time: undefined, point: undefined, seriesData: new Map() })
    expect(screen.getByTestId('cursor-tip')).not.toBeVisible()
  })

  it('is in the page colours swapped, and the point on the line is not the line colour', () => {
    const { chip } = places()
    expect(chip.style.background).toBe('var(--foreground)')
    expect(chip.style.color).toBe('var(--card)')
    const line = lib.seriesOptions[0]
    expect(line.crosshairMarkerBackgroundColor).toBeTruthy()
    expect(line.crosshairMarkerBackgroundColor).not.toBe(line.color)
  })
})

describe('hovering the price chart of a position', () => {
  it('shows the price above the cursor in the owner format, and nothing on the axis', async () => {
    mockApi({ '/api/v1/settings/general': GENERAL_US })
    renderAt(
      <PriceChart
        prices={[
          { date: '2024-01-03', close: '110' },
          { date: '2024-01-04', close: '1234.5' },
        ]}
        markers={[]}
        label="Price"
      />,
    )
    expect(lib.options.crosshair.horzLine.labelVisible).toBe(false)
    // the owner's number format arrives a moment after the chart is drawn
    await vi.waitFor(() => {
      hover(1234.5, 150, 90)
      expect(places().chip).toHaveTextContent(/1,234\.50/)
    })
    const { chip, left, top } = places()
    expect(chip).toBeVisible()
    expect(chip).toHaveTextContent('2024-01-04')
    expect(left).toBe('110px')
    expect(top).toBe('34px')
  })
})
