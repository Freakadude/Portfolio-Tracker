import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { Donut } from './dashboards/charts/Donut'
import { OTHER, colorOf, divergeFill, foldTail } from './dashboards/charts/palette'
import { squarify } from './dashboards/charts/Treemap'
import { REGISTRY, WIDGET_TYPES } from './dashboards/registry'
import { useLiveUpdates } from './dashboards/useLiveUpdates'
import {
  AllocationWidget,
  DriftBarsWidget,
  HoldingsTableWidget,
} from './dashboards/widgets/Composition'
import { PerformanceWidget } from './dashboards/widgets/History'
import {
  AttributionWidget,
  HeatmapWidget,
  IncomeWidget,
  MonthlyReturnsWidget,
} from './dashboards/widgets/Returns'
import { Markdown } from './dashboards/widgets/Simple'
import { Dashboards } from './pages/Dashboards'
import { Home } from './pages/Home'
import { GENERAL_US, mockApi, renderAt } from './test-utils'

vi.mock('lightweight-charts', () => {
  const series = () => ({ setData: vi.fn() })
  return {
    AreaSeries: 'area',
    CandlestickSeries: 'candles',
    ColorType: { Solid: 'solid' },
    HistogramSeries: 'histogram',
    LineSeries: 'line',
    PriceScaleMode: { Normal: 0, Logarithmic: 1 },
    createChart: () => ({
      addSeries: series,
      timeScale: () => ({ fitContent: vi.fn() }),
      subscribeCrosshairMove: vi.fn(),
      subscribeClick: vi.fn(),
      remove: vi.fn(),
    }),
    createSeriesMarkers: vi.fn(),
  }
})

afterEach(() => vi.unstubAllGlobals())

/** Shows where a click led, for drill-down tests. */
function Where() {
  const here = useLocation()
  return <p data-testid="where">{here.pathname + here.search}</p>
}
function page(ui: React.ReactElement) {
  return renderAt(
    <>
      {ui}
      <Where />
    </>,
  )
}
const where = () => screen.getByTestId('where').textContent

// --- the library -----------------------------------------------------------------------------

describe('the widget registry', () => {
  it('knows the twenty-two widgets of the library', () => {
    expect(WIDGET_TYPES).toHaveLength(22)
  })
  it('gives every chart a drill-down target (FR-DB-06)', () => {
    const charts = Object.values(REGISTRY).filter((d) => d.chart)
    expect(charts.length).toBeGreaterThanOrEqual(9)
    for (const def of charts) expect(def.drillsTo.length, def.type).toBeGreaterThan(5)
  })
  it('lets every widget with a period or scope say so', () => {
    expect(REGISTRY.kpi.scopes).toContain('sleeve')
    expect(REGISTRY.allocation.period).toBe(false)
    expect(REGISTRY.value_history.period).toBe(true)
  })
})

// --- chart helpers -----------------------------------------------------------------------------

describe('the treemap layout', () => {
  const items = [40, 25, 15, 10, 6, 4].map((value, i) => ({
    key: `k${i}`,
    value,
    weight: value / 100,
    color: 'red',
  }))
  it('fills the box exactly with tiles of the right area and none on top of another', () => {
    const tiles = squarify(items, 400, 250)
    expect(tiles).toHaveLength(6)
    const area = tiles.reduce((sum, t) => sum + t.w * t.h, 0)
    expect(area).toBeCloseTo(400 * 250, 3)
    for (const t of tiles) {
      expect(t.w * t.h).toBeCloseTo((t.item.value / 100) * 400 * 250, 3)
      expect(t.x).toBeGreaterThanOrEqual(-1e-9)
      expect(t.x + t.w).toBeLessThanOrEqual(400 + 1e-9)
      expect(t.y + t.h).toBeLessThanOrEqual(250 + 1e-9)
    }
    for (const a of tiles)
      for (const b of tiles) {
        if (a === b) continue
        const overlap =
          Math.max(0, Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x)) *
          Math.max(0, Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y))
        expect(overlap).toBeLessThan(1e-6)
      }
  })
  it('draws nothing for an empty or zero box', () => {
    expect(squarify([], 100, 100)).toEqual([])
    expect(squarify(items, 0, 100)).toEqual([])
  })
})

describe('colours', () => {
  it('folds the tail into Other and keeps the biggest', () => {
    const many = Array.from({ length: 9 }, (_, i) => ({ key: `k${i}`, value: 100 - i * 10 }))
    const folded = foldTail(many, 6, (_rest, value) => ({ key: OTHER, value }))
    expect(folded.map((f) => f.key)).toEqual(['k0', 'k1', 'k2', 'k3', 'k4', OTHER])
    expect(folded[5].value).toBe(50 + 40 + 30 + 20)
  })
  it("keeps a name's colour when the values change, and never gives a seventh a hue", () => {
    const keys = ['b', 'a', 'c']
    expect(colorOf(keys, 'a')).toBe('var(--series-1)')
    expect(colorOf(keys, 'b')).toBe('var(--series-2)')
    expect(colorOf([...keys, 'aa'], 'b')).toBe('var(--series-3)') // a new name sorts in
    const seven = ['a', 'b', 'c', 'd', 'e', 'f', 'g']
    expect(colorOf(seven, 'g')).toBe('var(--muted)')
    expect(colorOf(seven, OTHER)).toBe('var(--muted)')
  })
  it('is neutral at zero, blue above and red below', () => {
    expect(divergeFill(0, 0.1)).toContain('var(--diverge-pos) 0%')
    expect(divergeFill(0.05, 0.1)).toContain('var(--diverge-pos) 30%')
    expect(divergeFill(-0.1, 0.1)).toContain('var(--diverge-neg) 60%')
    expect(divergeFill(5, 0.1)).toContain('60%') // capped: text must stay readable
    expect(divergeFill(null, 1)).toBe('var(--diverge-mid)')
  })
})

describe('the note widget', () => {
  it('renders a small Markdown subset and never HTML', () => {
    render(<Markdown text={'# Plan\n- **buy** more\n- *wait*\n<script>alert(1)</script>'} />)
    expect(screen.getByText('Plan')).toBeInTheDocument()
    expect(screen.getByText('buy').tagName).toBe('STRONG')
    expect(screen.getByText('wait').tagName).toBe('EM')
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
    expect(screen.getByText('<script>alert(1)</script>')).toBeInTheDocument() // text, not a tag
    expect(document.querySelector('script')).toBeNull()
  })
})

// --- the widgets and their drill-downs (FR-DB-06) -----------------------------------------------

const slices = [
  {
    key: 'ETF',
    value_eur: '700',
    weight: '0.7',
    target: '0.5',
    drift_pp: '0.2',
    outside_band: true,
  },
  {
    key: 'Equity',
    value_eur: '300',
    weight: '0.3',
    target: null,
    drift_pp: null,
    outside_band: null,
  },
]

describe('allocation', () => {
  const data = {
    group_by: 'asset_class',
    chart: 'donut' as const,
    show_target: true,
    total_eur: '1000',
    slices,
  }
  it('opens the holdings filtered to the slice that was clicked', async () => {
    mockApi({ '/api/v1/settings/general': GENERAL_US })
    page(<AllocationWidget data={data} config={{}} filters={{}} />)
    await userEvent.click(screen.getByRole('button', { name: /^ETF: 70[.,]0%/ }))
    expect(where()).toBe('/holdings?group_by=asset_class&value=ETF')
  })
  it('can be read as a table, with the drift', async () => {
    mockApi({ '/api/v1/settings/general': GENERAL_US })
    page(<AllocationWidget data={data} config={{}} filters={{}} />)
    await userEvent.click(screen.getByRole('button', { name: 'Show data as a table' }))
    const table = screen.getByRole('table', { name: 'Allocation' })
    expect(
      within(table).getByRole('row', { name: /ETF.*70[.,]0%.*50[.,]0%.*20[.,]0 pp/ }),
    ).toBeInTheDocument()
  })
  it('names a group over its target', async () => {
    mockApi({ '/api/v1/settings/general': GENERAL_US })
    page(<AllocationWidget data={data} config={{}} filters={{}} />)
    expect(screen.getByText('outside the band')).toBeInTheDocument()
  })
  it('says why look-through is not available yet', () => {
    mockApi({ '/api/v1/settings/general': GENERAL_US })
    page(
      <AllocationWidget
        data={{ unavailable: true, reason: 'Needs ETF data (Phase 4).' }}
        config={{}}
        filters={{}}
      />,
    )
    expect(screen.getByText('Needs ETF data (Phase 4).')).toBeInTheDocument()
  })
  it('folds more than six slices into Other, which does not drill down', async () => {
    mockApi({ '/api/v1/settings/general': GENERAL_US })
    const many = Array.from({ length: 9 }, (_, i) => ({
      key: `Fund ${i}`,
      value_eur: String(100 - i),
      weight: '0.1',
      target: null,
      drift_pp: null,
      outside_band: null,
    }))
    page(<AllocationWidget data={{ ...data, slices: many }} config={{}} filters={{}} />)
    expect(screen.getAllByRole('button')).toHaveLength(5 + 1) // five slices that open something, and the table toggle
    await userEvent.click(screen.getByRole('img', { name: /^Other:/ }))
    expect(where()).toBe('/')
  })
})

describe('the donut', () => {
  it('can be used from the keyboard', async () => {
    const onSelect = vi.fn()
    render(
      <Donut
        slices={[{ key: 'A', value: 5, weight: 1, color: 'red' }]}
        centerLabel="Total"
        format={(v) => String(v)}
        formatWeight={(w) => `${w * 100}%`}
        label="x"
        onSelect={onSelect}
      />,
    )
    const slice = screen.getByRole('button', { name: /^A:/ })
    slice.focus()
    await userEvent.keyboard('{Enter}')
    expect(onSelect).toHaveBeenCalledWith('A')
  })
})

describe('the holdings table', () => {
  it('shows one line per instrument and never the account, even for an older dashboard', () => {
    const row = {
      instrument_id: 7,
      name: 'ASML Holding',
      account: 'Degiro, Pension',
      asset_class: 'EQUITY',
      sleeve: null,
      quantity: '10',
      avg_cost_eur: '100',
      cost_basis_eur: '1000',
      close: '110',
      close_date: '2024-04-10',
      stale: false,
      value: '1100',
      weight: '0.5',
      unrealized: '100',
      unrealized_ratio: '0.1',
      day: '5',
      day_ratio: '0.004',
      total_return: '100',
      income: '0',
    }
    page(
      <HoldingsTableWidget
        data={
          {
            columns: ['name', 'account', 'quantity'],
            group_by: 'account',
            rows: [row],
            totals: {},
          } as never
        }
        config={{ group_by: 'account' }}
        filters={{}}
      />,
    )
    expect(screen.getByRole('columnheader', { name: 'Instrument' })).toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: 'Account' })).toBeNull()
    expect(screen.queryByRole('rowheader')).toBeNull() // no group heading
    expect(screen.getAllByRole('link', { name: 'ASML Holding' })).toHaveLength(1)
    expect(screen.queryByText('Degiro, Pension')).toBeNull()
  })
})

describe('drift', () => {
  it('opens the holdings of a sleeve', async () => {
    mockApi({ '/api/v1/settings/general': GENERAL_US })
    page(
      <DriftBarsWidget
        data={{
          bars: [
            {
              key: 'core',
              weight: '1',
              target: '0.6',
              drift_pp: '0.4',
              band: '0.05',
              outside_band: true,
            },
          ],
        }}
        config={{}}
        filters={{}}
      />,
    )
    await userEvent.click(screen.getByRole('button', { name: /^core: \+40[.,]0 pp/ }))
    expect(where()).toBe('/holdings?group_by=sleeve&value=core')
  })
})

describe('performance comparison', () => {
  it('suggests a benchmark while none is chosen (Q9)', async () => {
    mockApi({ '/api/v1/settings/general': GENERAL_US })
    page(
      <PerformanceWidget
        data={{
          suggest_benchmark: true,
          series: [
            {
              key: 'portfolio',
              label: 'Portfolio',
              points: [{ date: '2024-01-02', value: '100' }],
            },
          ],
        }}
        config={{}}
        filters={{}}
      />,
    )
    expect(screen.getByText(/No benchmark chosen yet/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open instruments' })).toHaveAttribute(
      'href',
      '/holdings',
    )
  })
})

describe('attribution (FR-PF-07)', () => {
  const rows = [
    { key: '7', name: 'Acme', pnl_eur: '90', points: '0.0612' },
    { key: '9', name: 'Beta', pnl_eur: '-30', points: '-0.0204' },
    { key: 'other', name: 'Other (costs and interest)', pnl_eur: '-2', points: '-0.0014' },
  ]

  it('shows points on the bars, opens the position, and gives euro and points in the table', async () => {
    mockApi({ '/api/v1/settings/general': GENERAL_US })
    page(
      <AttributionWidget
        data={{ total_return: '0.0394', portfolio_pnl_eur: '58', rows }}
        config={{}}
        filters={{}}
      />,
    )
    await userEvent.click(screen.getByRole('button', { name: /^Acme: \+6[.,]1 pp/ }))
    expect(where()).toBe('/holdings?group_by=instrument&value=Acme')
    expect(screen.getByText(/Return of the period/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Show data as a table' }))
    const table = screen.getByRole('table', { name: 'Contribution to return' })
    expect(within(table).getByText('Beta').closest('tr')).toHaveTextContent(/30[.,]00.*-2[.,]04 pp/)
  })

  it('falls back to euro when there are no points to show', () => {
    mockApi({ '/api/v1/settings/general': GENERAL_US })
    page(
      <AttributionWidget
        data={{ total_return: null, portfolio_pnl_eur: '58', rows: [{ ...rows[0], points: null }] }}
        config={{}}
        filters={{}}
      />,
    )
    expect(screen.getByRole('button', { name: /^Acme: \+.*90/ })).toBeInTheDocument()
  })
})

describe('returns', () => {
  it('opens a position from the heatmap and shows the sign as well as the colour', async () => {
    mockApi({ '/api/v1/settings/general': GENERAL_US })
    page(
      <HeatmapWidget
        data={{
          cells: [
            { instrument_id: 7, name: 'Acme', twr: '-0.042', pnl_eur: '-42', value_eur: '958' },
          ],
        }}
        config={{}}
        filters={{}}
      />,
    )
    const cell = screen.getByRole('button', { name: /^Acme: -4[.,]20%/ })
    expect(cell).toHaveTextContent(/−4[.,]2%/)
    await userEvent.click(cell)
    expect(where()).toBe('/holdings/7')
  })
  it('opens the transactions of a month from the monthly grid and from the income chart', async () => {
    mockApi({ '/api/v1/settings/general': GENERAL_US })
    page(
      <MonthlyReturnsWidget
        data={{ years: [{ year: 2024, months: { '2': '0.031' }, total: '0.031' }] }}
        config={{}}
        filters={{}}
      />,
    )
    await userEvent.click(screen.getByRole('button', { name: /^2024-02:/ }))
    expect(where()).toBe('/transactions?from=2024-02-01&to=2024-02-29') // a leap year
  })
  it('stacks dividends and interest by month', async () => {
    mockApi({ '/api/v1/settings/general': GENERAL_US })
    page(
      <IncomeWidget
        data={{ total_eur: '8', months: [{ month: '2024-03', dividends: '5', interest: '3' }] }}
        config={{}}
        filters={{}}
      />,
    )
    const column = screen.getByRole('button', {
      name: /^2024-03: Dividends \u20ac\s5, Interest \u20ac\s3/,
    })
    await userEvent.click(column)
    expect(where()).toBe('/transactions?from=2024-03-01&to=2024-03-31')
    expect(screen.getByText(/Received/)).toBeInTheDocument()
  })
})

// --- a dashboard on Home (FR-DB-01 to FR-DB-05) -------------------------------------------------

const KPI = {
  type: 'kpi',
  config: {
    metric: 'value',
    scope: { kind: 'portfolio', id: null },
    period: null,
    follow_filters: true,
    sparkline: true,
    title: null,
  },
}
const NOTE = {
  type: 'note',
  config: {
    text: 'Check **fees**',
    title: 'Reminder',
    scope: { kind: 'portfolio', id: null },
    period: null,
    follow_filters: true,
  },
}

function dashboard(over: Record<string, unknown> = {}) {
  return {
    id: 1,
    name: 'Overview',
    is_default: true,
    sort_order: 1,
    filters: { period: 'YTD', account: null },
    widgets: [
      { id: 10, ...KPI, grid: { x: 0, y: 0, w: 3, h: 2 } },
      { id: 11, ...NOTE, grid: { x: 3, y: 0, w: 4, h: 3 } },
    ],
    layouts: {
      lg: [
        { i: '10', x: 0, y: 0, w: 3, h: 2 },
        { i: '11', x: 3, y: 0, w: 4, h: 3 },
      ],
      md: [
        { i: '10', x: 0, y: 0, w: 2, h: 2 },
        { i: '11', x: 2, y: 0, w: 3, h: 3 },
      ],
      sm: [
        { i: '10', x: 0, y: 0, w: 1, h: 2 },
        { i: '11', x: 0, y: 2, w: 1, h: 3 },
      ],
    },
    ...over,
  }
}

const ACCOUNT = {
  id: 1,
  name: 'Degiro',
  broker: null,
  cost_basis_method: 'FIFO',
  base_currency: 'EUR',
  active: true,
  track_cash: false,
  transaction_count: 3,
}

function answerWidgets(request: Request) {
  return request
    .json()
    .then((body: { requests: { key: string; type: string }[]; filters: unknown }) => ({
      results: Object.fromEntries(
        body.requests.map((r) => [
          r.key,
          r.type === 'kpi'
            ? {
                data: {
                  metric: 'value',
                  kind: 'eur',
                  value: '1188',
                  sparkline: [],
                  as_of: '2024-01-15',
                },
              }
            : { data: { text: 'Check **fees**' } },
        ]),
      ),
    }))
}

function home(extra: Record<string, unknown> = {}) {
  return mockApi({
    '/api/v1/settings/general': GENERAL_US,
    '/api/v1/accounts': [ACCOUNT],
    '/api/v1/dashboards/default': dashboard(),
    'GET /api/v1/dashboards': [
      { id: 1, name: 'Overview', is_default: true, sort_order: 1, widget_count: 2 },
    ],
    'POST /api/v1/widgets/data': answerWidgets,
    ...extra,
  })
}

describe('Home', () => {
  it('tells a new owner what to do first', async () => {
    mockApi({
      '/api/v1/settings/general': GENERAL_US,
      '/api/v1/accounts': [{ ...ACCOUNT, transaction_count: 0 }],
    })
    renderAt(<Home />)
    expect(
      await screen.findByText('Add your first instrument to start tracking your portfolio.'),
    ).toBeInTheDocument()
  })

  it('shows the default dashboard with the data of its widgets', async () => {
    home()
    renderAt(<Home />)
    expect(await screen.findByRole('heading', { level: 1, name: 'Overview' })).toBeInTheDocument()
    expect(await screen.findByText('€1,188.00')).toBeInTheDocument()
    expect(await screen.findByText('fees')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Reminder' })).toBeInTheDocument() // its own title
    expect(screen.getByRole('region', { name: 'Value' })).toBeInTheDocument()
  })

  it('asks for all the widgets in one request, with the dashboard filters (FR-DB-05)', async () => {
    const { calls } = home()
    renderAt(<Home />)
    await screen.findByText('€1,188.00')
    const asked = calls.filter((c) => c.path === '/api/v1/widgets/data')
    expect(asked).toHaveLength(1)
    expect(asked[0].body).toMatchObject({
      requests: [
        { key: '10', type: 'kpi' },
        { key: '11', type: 'note' },
      ],
      filters: { period: 'YTD', account: null },
    })
    await userEvent.click(screen.getByRole('button', { name: '1 month' }))
    await waitFor(() => {
      const last = calls.filter((c) => c.path === '/api/v1/widgets/data').at(-1)
      expect(last?.body).toMatchObject({ filters: { period: '1M' } })
    })
  })

  it('does not ask for a custom period before both dates are chosen', async () => {
    const { calls } = home()
    renderAt(<Home />)
    await screen.findByText('€1,188.00')
    await userEvent.click(screen.getByRole('button', { name: 'Custom' }))
    expect(screen.getByText(/Pick a start and an end date/)).toBeInTheDocument()
    const last = calls.filter((c) => c.path === '/api/v1/widgets/data').at(-1)
    expect(last?.body).toMatchObject({ filters: { period: 'YTD' } }) // still the year to date
    await userEvent.type(screen.getByLabelText('From'), '2024-01-02')
    await userEvent.type(screen.getByLabelText('To'), '2024-01-12')
    await waitFor(() => {
      const next = calls.filter((c) => c.path === '/api/v1/widgets/data').at(-1)
      expect(next?.body).toMatchObject({
        filters: { period: 'CUSTOM', start: '2024-01-02', end: '2024-01-12' },
      })
    })
  })

  it('shows the editing controls only in edit mode', async () => {
    home()
    renderAt(<Home />)
    await screen.findByText('€1,188.00')
    expect(screen.queryByRole('button', { name: /^Settings of/ })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Edit' }))
    expect(screen.getByRole('button', { name: 'Settings of Reminder' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Move Reminder' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add widget' })).toBeInTheDocument()
  })

  it('removes a widget after confirmation', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const { calls } = home({
      'DELETE /api/v1/dashboards/1/widgets/11': dashboard({
        widgets: [{ id: 10, ...KPI, grid: { x: 0, y: 0, w: 3, h: 2 } }],
      }),
    })
    renderAt(<Home />)
    await screen.findByText('€1,188.00')
    await userEvent.click(screen.getByRole('button', { name: 'Edit' }))
    await userEvent.click(screen.getByRole('button', { name: 'Remove Reminder' }))
    await waitFor(() =>
      expect(calls.some((c) => c.method === 'DELETE' && c.path.endsWith('/widgets/11'))).toBe(true),
    )
  })

  it('changes a widget and redraws the preview within 300 ms on cached data (FR-DB-03)', async () => {
    const { calls } = home({
      'PATCH /api/v1/dashboards/1/widgets/10': dashboard(),
      'POST /api/v1/widgets/data': (request: Request) =>
        request
          .json()
          .then((body: { requests: { key: string; config: { metric?: string } }[] }) => ({
            results: Object.fromEntries(
              body.requests.map((r) => [
                r.key,
                r.key === '11'
                  ? { data: { text: 'Check' } }
                  : {
                      data: {
                        metric: r.config.metric ?? 'value',
                        kind: 'eur',
                        value: r.config.metric === 'twr' ? '5' : '1188',
                        sparkline: [],
                      },
                    },
              ]),
            ),
          })),
    })
    renderAt(<Home />)
    await screen.findByText('€1,188.00')
    await userEvent.click(screen.getByRole('button', { name: 'Edit' }))
    await userEvent.click(screen.getByRole('button', { name: 'Settings of Value' }))
    const dialog = await screen.findByRole('dialog', { name: /Settings of Value/ })
    await within(dialog).findByText('Preview')
    const started = performance.now()
    await userEvent.selectOptions(within(dialog).getByLabelText('Figure'), 'twr')
    await within(dialog).findByText('Return (time-weighted)')
    expect(performance.now() - started).toBeLessThan(300 + 250) // typing and the 150 ms debounce included
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true))
    expect(calls.find((c) => c.method === 'PATCH')?.body).toMatchObject({
      config: { metric: 'twr' },
    })
  })

  it('lets the position be typed, for people who cannot drag (keyboard)', async () => {
    const { calls } = home({
      'PATCH /api/v1/dashboards/1/widgets/10': dashboard(),
      'PUT /api/v1/dashboards/1/layout': dashboard(),
    })
    renderAt(<Home />)
    await screen.findByText('€1,188.00')
    await userEvent.click(screen.getByRole('button', { name: 'Edit' }))
    await userEvent.click(screen.getByRole('button', { name: 'Settings of Value' }))
    const dialog = await screen.findByRole('dialog')
    const width = within(dialog).getByLabelText('Width (columns)')
    await userEvent.clear(width)
    await userEvent.type(width, '6')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PUT')).toBe(true))
    const layout = calls.find((c) => c.method === 'PUT')?.body as {
      layouts: Record<string, { i: string; w: number }[]>
    }
    expect(layout.layouts.lg.find((b) => b.i === '10')?.w).toBe(6)
    expect(layout.layouts.sm.find((b) => b.i === '10')?.w).toBe(1) // the phone layout is left alone
  })

  it('reports a widget that cannot be drawn next to the ones that can', async () => {
    home({
      'POST /api/v1/widgets/data': {
        results: {
          '10': { data: { metric: 'value', kind: 'eur', value: '1188', sparkline: [] } },
          '11': { error: 'Choose which sleeve this widget should show.' },
        },
      },
    })
    renderAt(<Home />)
    expect(await screen.findByText('€1,188.00')).toBeInTheDocument()
    expect(await screen.findByRole('alert')).toHaveTextContent('Choose which sleeve')
  })
})

// --- the list of dashboards (FR-DB-01, FR-DB-07) ------------------------------------------------

describe('copying a widget and removing filter bars (edit mode)', () => {
  beforeEach(() => localStorage.clear())

  it('copies a widget with its settings and size, under the others, and marks a titled copy', async () => {
    const { calls } = home({ 'POST /api/v1/dashboards/1/widgets': dashboard() })
    renderAt(<Home />)
    await screen.findByText('€1,188.00')
    expect(screen.queryByRole('button', { name: /^Duplicate/ })).toBeNull() // only when editing
    await userEvent.click(screen.getByRole('button', { name: 'Edit' }))

    await userEvent.click(screen.getByRole('button', { name: 'Duplicate Reminder' }))
    await vi.waitFor(() =>
      expect(calls.some((c) => c.method === 'POST' && c.path.endsWith('/widgets'))).toBe(true),
    )
    const body = calls.find((c) => c.method === 'POST' && c.path.endsWith('/widgets'))?.body as {
      type: string
      config: Record<string, unknown>
      grid: Record<string, number>
    }
    expect(body.type).toBe('note')
    expect(body.config).toMatchObject({ text: 'Check **fees**', title: 'Reminder (copy)' })
    // the same size as the original (4 wide, 3 high), below the lowest widget (it ends at row 3)
    expect(body.grid).toEqual({ x: 3, y: 3, w: 4, h: 3 })
  })

  it('removes the timeframe bar, keeps the period, and adds it back', async () => {
    const { calls } = home({
      'PATCH /api/v1/dashboards/1': dashboard(),
    })
    renderAt(<Home />)
    await screen.findByText('€1,188.00')
    expect(screen.queryByRole('button', { name: 'Remove the timeframe filter' })).toBeNull()
    expect(screen.getByRole('group', { name: 'Period' })).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: 'Edit' }))

    await userEvent.click(screen.getByRole('button', { name: 'Remove the timeframe filter' }))
    expect(screen.queryByRole('group', { name: 'Period' })).toBeNull()
    expect(screen.getByText('Timeframe filter removed.')).toBeVisible()
    expect(screen.getByText(/keep using This year/)).toBeVisible() // the period it had
    await vi.waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true))
    expect(calls.find((c) => c.method === 'PATCH')?.body).toMatchObject({
      filters: { period: 'YTD', hidden: ['timeframe'] },
    })

    await userEvent.click(screen.getByRole('button', { name: 'Add it back' }))
    expect(screen.getByRole('group', { name: 'Period' })).toBeVisible()
    expect(screen.queryByText('Timeframe filter removed.')).toBeNull()
  })

  it('opens a dashboard saved without its filter bars without them, and offers them back only when editing', async () => {
    home({
      '/api/v1/dashboards/default': dashboard({
        filters: { period: 'YTD', account: null, hidden: ['timeframe', 'scope'] },
      }),
    })
    renderAt(<Home />)
    await screen.findByText('€1,188.00')
    expect(screen.queryByRole('group', { name: 'Period' })).toBeNull()
    expect(screen.queryByText('Timeframe filter removed.')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Edit' }))
    expect(screen.getByText('Timeframe filter removed.')).toBeVisible()
    expect(screen.getByText('Account and instruments filter removed.')).toBeVisible()
  })
})

describe('choosing a dashboard for the Dashboards tab', () => {
  beforeEach(() => localStorage.clear())

  it('is a switch on the dashboard, kept in this browser, and the list stays one click away', async () => {
    home()
    renderAt(<Home />)
    await screen.findByText('€1,188.00')
    const button = screen.getByRole('button', { name: 'Open this from the Dashboards tab' })
    expect(button).toHaveAttribute('aria-pressed', 'false')
    await userEvent.click(button)
    expect(localStorage.getItem('folio.dashboards.tab')).toBe('1')
    const on = screen.getByRole('button', { name: 'Dashboards tab opens this one' })
    expect(on).toHaveAttribute('aria-pressed', 'true')
    await userEvent.click(on)
    expect(localStorage.getItem('folio.dashboards.tab')).toBeNull()
    expect(screen.getByRole('link', { name: 'All dashboards' })).toHaveAttribute(
      'href',
      '/dashboards/all',
    )
  })
})

describe('the dashboards page', () => {
  const list = [
    { id: 1, name: 'Overview', is_default: true, sort_order: 1, widget_count: 7 },
    { id: 2, name: 'Risk', is_default: false, sort_order: 2, widget_count: 7 },
  ]
  const templates = [
    {
      key: 'overview',
      name: 'Overview',
      description: 'Value, result and allocation.',
      widget_count: 7,
    },
    { key: 'risk', name: 'Risk', description: 'Volatility and drawdown.', widget_count: 7 },
  ]
  function pageApi(extra: Record<string, unknown> = {}) {
    return mockApi({
      '/api/v1/settings/general': GENERAL_US,
      'GET /api/v1/dashboards': list,
      '/api/v1/dashboard-templates': templates,
      ...extra,
    })
  }

  it('lists the dashboards and marks the one Home opens', async () => {
    pageApi()
    renderAt(<Dashboards />)
    const table = await screen.findByRole('table', { name: 'Your dashboards' })
    expect(within(table).getByRole('row', { name: /Overview.*Opens on Home/ })).toBeInTheDocument()
    expect(
      within(table).queryByRole('button', { name: 'Open on Home', hidden: false }),
    ).toBeInTheDocument() // only for Risk
  })

  it('creates a dashboard from a template', async () => {
    const { calls } = pageApi({ 'POST /api/v1/dashboards': dashboard({ id: 3, name: 'Risk' }) })
    renderAt(<Dashboards />)
    const picker = await screen.findByLabelText('Start from')
    await screen.findByRole('option', { name: 'Risk' })
    await userEvent.selectOptions(picker, 'risk')
    expect(screen.getByText('Volatility and drawdown.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Create dashboard' }))
    await waitFor(() =>
      expect(calls.some((c) => c.method === 'POST' && c.path === '/api/v1/dashboards')).toBe(true),
    )
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ name: 'Risk', template: 'risk' })
  })

  it('reorders, duplicates and deletes after asking', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const { calls } = pageApi({
      'PUT /api/v1/dashboards/order': list,
      'POST /api/v1/dashboards/2/duplicate': dashboard({ id: 4 }),
      'DELETE /api/v1/dashboards/2': new Response(null, { status: 204 }),
    })
    renderAt(<Dashboards />)
    await userEvent.click(await screen.findByRole('button', { name: 'Move Risk up' }))
    await waitFor(() =>
      expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({ ids: [2, 1] }),
    )
    const row = screen.getByRole('row', { name: /^Risk/ })
    await userEvent.click(within(row).getByRole('button', { name: 'Duplicate' }))
    await waitFor(() =>
      expect(calls.some((c) => c.path === '/api/v1/dashboards/2/duplicate')).toBe(true),
    )
    await userEvent.click(within(row).getByRole('button', { name: 'Delete' }))
    await waitFor(() =>
      expect(calls.some((c) => c.method === 'DELETE' && c.path === '/api/v1/dashboards/2')).toBe(
        true,
      ),
    )
  })

  it('imports a dashboard file, and explains a file that is not JSON', async () => {
    const { calls } = pageApi({ 'POST /api/v1/dashboards/import': dashboard({ id: 5 }) })
    renderAt(<Dashboards />)
    const input = await screen.findByLabelText('Dashboard file')
    await userEvent.upload(input, new File(['not json'], 'x.json', { type: 'application/json' }))
    expect(
      await screen.findByText('This file is not a Folio dashboard export.'),
    ).toBeInTheDocument()
    const document = { format: 'folio-dashboard', version: 1, widgets: [] }
    await userEvent.upload(
      input,
      new File([JSON.stringify(document)], 'ok.json', { type: 'application/json' }),
    )
    await waitFor(() =>
      expect(calls.some((c) => c.path === '/api/v1/dashboards/import')).toBe(true),
    )
    expect(calls.find((c) => c.path === '/api/v1/dashboards/import')?.body).toEqual({ document })
  })
})

// --- live updates (FR-DB-04) --------------------------------------------------------------------

describe('live updates', () => {
  it('refreshes the widgets when the worker reports a new close', () => {
    const sources: FakeSource[] = []
    class FakeSource {
      listeners = new Map<string, () => void>()
      closed = false
      constructor(public url: string) {
        sources.push(this)
      }
      addEventListener(type: string, fn: () => void) {
        this.listeners.set(type, fn)
      }
      close() {
        this.closed = true
      }
    }
    vi.stubGlobal('EventSource', FakeSource)
    const client = new QueryClient()
    const spy = vi.spyOn(client, 'invalidateQueries')
    function Probe() {
      useLiveUpdates()
      return null
    }
    const { unmount } = render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <Routes>
            <Route path="*" element={<Probe />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(sources[0].url).toBe('/api/v1/events')
    sources[0].listeners.get('price_update')?.()
    const keys = spy.mock.calls.map((c) => (c[0] as { queryKey: string[] }).queryKey[0])
    expect(keys).toEqual(expect.arrayContaining(['widget-data', 'positions', 'portfolio']))
    sources[0].listeners.get('job_status')?.()
    expect(spy.mock.calls.at(-1)?.[0]).toEqual({ queryKey: ['system'] })
    unmount()
    expect(sources[0].closed).toBe(true)
  })
})
