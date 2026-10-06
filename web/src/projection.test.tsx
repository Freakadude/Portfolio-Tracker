import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ProjectionWidget } from './dashboards/widgets/Projection'
import { Reports } from './pages/Reports'
import { GENERAL_US, mockApi, renderAt } from './test-utils'

// The chart draws on a canvas, which jsdom does not have: record what it is asked to draw.
const chart = vi.hoisted(() => ({
  addSeries: vi.fn(),
  setData: vi.fn(),
  created: vi.fn(),
}))
vi.mock('lightweight-charts', () => ({
  ColorType: { Solid: 'solid' },
  PriceScaleMode: { Normal: 0, Logarithmic: 1 },
  AreaSeries: 'area',
  LineSeries: 'line',
  CandlestickSeries: 'candles',
  HistogramSeries: 'histogram',
  createChart: (...args: unknown[]) => {
    chart.created(...args)
    return {
      addSeries: (kind: string, options: unknown) => {
        chart.addSeries(kind, options)
        return { setData: chart.setData }
      },
      timeScale: () => ({ fitContent: vi.fn() }),
      subscribeCrosshairMove: vi.fn(),
      subscribeClick: vi.fn(),
      remove: vi.fn(),
    }
  },
  createSeriesMarkers: vi.fn(),
}))

beforeEach(() => vi.clearAllMocks())
afterEach(() => vi.unstubAllGlobals())

const POINT = (month: number, date: string, median: string) => ({
  month,
  date,
  invested_eur: String(2500 + 100 * month),
  p10_eur: String(Number(median) - 300),
  median_eur: median,
  p90_eur: String(Number(median) + 400),
})

const PROJECTION = {
  assumptions: {
    start_value_eur: '2500',
    monthly_contribution_eur: '100',
    annual_return_pct: '5',
    annual_volatility_pct: '15',
    years: 2,
    paths: 2000,
    seed: 1,
  },
  as_of: '2026-10-06',
  points: [
    POINT(0, '2026-10-06', '2500'),
    POINT(12, '2027-10-06', '3900'),
    POINT(24, '2028-10-06', '5400'),
  ],
  measured: {
    start: '2025-10-06',
    end: '2026-10-06',
    annual_return_pct: '7.5',
    annual_volatility_pct: '12.25',
  },
  note: 'An illustration, not a forecast.',
}

const routes = (extra: Record<string, unknown> = {}) => ({
  '/api/v1/settings/general': GENERAL_US,
  '/api/v1/accounts': [],
  '/api/v1/portfolio/projection': PROJECTION,
  ...extra,
})

describe('the projection tab (FR-PF-12)', () => {
  it('draws the median, the band and what was paid in, and states the assumptions', async () => {
    mockApi(routes())
    renderAt(<Reports />, '/reports?tab=projection')
    expect(
      await screen.findByRole('region', { name: 'Projected value of the portfolio' }),
    ).toBeVisible()
    await waitFor(() => expect(chart.addSeries).toHaveBeenCalledTimes(4)) // band, mask, median, paid in
    expect(chart.addSeries.mock.calls.map((c) => c[0])).toEqual(['area', 'area', 'line', 'line'])
    expect(
      screen.getByText(
        /Assumptions: start \$?€?2,500.*100 a month, 5\.0 % expected return and 15\.0 % volatility a year, 2 years, 2000 simulated paths/,
      ),
    ).toBeInTheDocument()
    expect(screen.getByText(/the median is .*5,400/)).toBeInTheDocument()
    expect(
      screen.getByText(/returned 7\.5 % a year with a volatility of 12\.3 %/),
    ).toBeInTheDocument()
  })

  it('reads as a table too (every chart can)', async () => {
    mockApi(routes())
    renderAt(<Reports />, '/reports?tab=projection')
    await screen.findByRole('region', { name: 'Projected value of the portfolio' })
    await userEvent.click(screen.getByRole('button', { name: 'Show data as a table' }))
    const table = await screen.findByRole('table', {
      name: 'Projected value of the portfolio by month',
    })
    const rows = within(table).getAllByRole('row')
    expect(rows).toHaveLength(4)
    expect(rows[3]).toHaveTextContent('2028-10-06')
    expect(rows[3]).toHaveTextContent('€5,400.00')
    expect(rows[3]).toHaveTextContent('€5,100.00') // the 10th percentile
  })

  it('asks again when an assumption changes, and refuses nonsense without asking', async () => {
    const { calls } = mockApi(routes())
    renderAt(<Reports />, '/reports?tab=projection')
    await screen.findByRole('region', { name: 'Projected value of the portfolio' })
    const asked = () => calls.filter((c) => c.path === '/api/v1/portfolio/projection').length
    const before = asked()
    await userEvent.clear(screen.getByLabelText('Added each month (€)'))
    await userEvent.type(screen.getByLabelText('Added each month (€)'), '250')
    await waitFor(() => expect(asked()).toBeGreaterThan(before))
    const afterValid = asked()
    await userEvent.clear(screen.getByLabelText('Years ahead (1 to 40)'))
    await userEvent.click(screen.getByLabelText('Years ahead (1 to 40)'))
    await userEvent.paste('99')
    expect(await screen.findByText(/horizon is 1 to 40 whole years/)).toBeInTheDocument()
    expect(asked()).toBe(afterValid)
  })

  it('shows the way to Reports from the widget library: the widget draws or says why not', async () => {
    mockApi(routes())
    const props = { config: {}, filters: { period: 'YTD', account: null } }
    const none = renderAt(
      <ProjectionWidget
        {...props}
        data={{ empty: true, reason: 'There is nothing to project yet: no transactions.' }}
      />,
    )
    expect(screen.getByText(/nothing to project yet/)).toBeInTheDocument()
    none.unmount()
    renderAt(
      <ProjectionWidget
        {...props}
        data={{
          assumptions: PROJECTION.assumptions,
          points: PROJECTION.points.map((p) => ({
            date: p.date,
            invested: p.invested_eur,
            p10: p.p10_eur,
            median: p.median_eur,
            p90: p.p90_eur,
          })),
        }}
      />,
    )
    await waitFor(() => expect(chart.addSeries).toHaveBeenCalledTimes(4))
    expect(await screen.findByText(/5[.,]0 % expected return/)).toBeInTheDocument() // stays visible
  })
})
