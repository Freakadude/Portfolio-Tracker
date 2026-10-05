import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Bell } from './components/Bell'
import { MacroWidget } from './dashboards/widgets/Macro'
import { Inbox } from './notify/Inbox'
import { MacroTab } from './notify/MacroTab'
import { NotificationsTab } from './notify/NotificationsTab'
import { PriceAlerts } from './notify/PriceAlerts'
import { SystemInfo } from './notify/SystemInfo'
import { GENERAL_US, mockApi, renderAt } from './test-utils'

vi.mock('lightweight-charts', () => {
  const series = () => ({ setData: vi.fn(), applyOptions: vi.fn() })
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
      priceScale: () => ({ applyOptions: vi.fn() }),
    }),
    createSeriesMarkers: vi.fn(),
  }
})

afterEach(() => vi.unstubAllGlobals())

const delivery = (over: Record<string, unknown> = {}) => ({
  id: 1,
  notification_id: 1,
  channel: 'home_assistant',
  status: 'sent',
  attempts: 1,
  last_error: null,
  sent_at: '2026-10-05T08:02:00Z',
  next_attempt_at: null,
  merged_into_id: null,
  ...over,
})
const item = (over: Record<string, unknown> = {}) => ({
  id: 1,
  source: 'signal',
  subject: 'equity',
  severity: 'high',
  title: 'equity is 12.0 pp over its target',
  body: 'equity weighs 62% against 50%.',
  link: '/strategies',
  created_at: '2026-10-05T08:00:00Z',
  read_at: null,
  deliveries: [
    delivery(),
    delivery({
      id: 2,
      channel: 'ntfy',
      status: 'failed',
      attempts: 3,
      last_error: 'ntfy answered HTTP 502.',
    }),
  ],
  ...over,
})

describe('the inbox (FR-NT-01)', () => {
  it('shows the unread count on the bell', async () => {
    mockApi({ '/api/v1/notifications/unread': { unread: 3 } })
    renderAt(<Bell />)
    const bell = await screen.findByRole('link', { name: 'Inbox: 3 unread' })
    expect(bell).toHaveAttribute('href', '/insights')
    expect(bell).toHaveTextContent('3')
  })

  it('lists items with their deliveries, filters them and marks chosen ones read', async () => {
    const { calls } = mockApi({
      '/api/v1/notifications': (request: Request) => {
        const severity = new URL(request.url).searchParams.get('severity')
        const items = [
          item(),
          item({
            id: 2,
            severity: 'low',
            subject: 'gold',
            title: 'Review the thesis for gold',
            deliveries: [],
          }),
        ]
        return {
          items: severity ? items.filter((i) => i.severity === severity) : items,
          total: 2,
          unread: 2,
        }
      },
      'POST /api/v1/notifications/read': { unread: 1 },
    })
    renderAt(<Inbox />)
    const first = await screen.findByRole('listitem', { name: 'equity is 12.0 pp over its target' })
    expect(first).toHaveTextContent(/Sent to Home Assistant at/)
    expect(first).toHaveTextContent('ntfy failed: ntfy answered HTTP 502.')
    expect(within(first).getByRole('link', { name: 'Open' })).toHaveAttribute('href', '/strategies')
    expect(screen.getByText('2 unread')).toBeInTheDocument()

    await userEvent.selectOptions(screen.getByLabelText('Severity'), 'low')
    await waitFor(() =>
      expect(screen.queryByRole('listitem', { name: /equity/ })).not.toBeInTheDocument(),
    )
    expect(calls.some((c) => c.path === '/api/v1/notifications')).toBe(true)

    await userEvent.click(screen.getByLabelText('Choose Review the thesis for gold'))
    await userEvent.click(screen.getByRole('button', { name: 'Mark 1 as read' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({
      ids: [2],
      all: false,
      read: true,
    })
  })

  it('marks everything read at once', async () => {
    const { calls } = mockApi({
      '/api/v1/notifications': { items: [item()], total: 1, unread: 1 },
      'POST /api/v1/notifications/read': { unread: 0 },
    })
    renderAt(<Inbox />)
    await userEvent.click(await screen.findByRole('button', { name: 'Mark all as read' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ ids: [], all: true, read: true })
  })
})

describe('notification settings (FR-NT-02, FR-NT-03, FR-NT-08)', () => {
  const section = {
    channel: 'home_assistant',
    routing: {
      critical: ['home_assistant', 'ntfy'],
      high: ['home_assistant', 'ntfy'],
      medium: ['home_assistant', 'ntfy'],
      low: [],
      info: [],
      digest: ['home_assistant', 'ntfy'],
    },
    quiet_hours_start: '22:00',
    quiet_hours_end: '07:30',
    daily_push_cap: 5,
    push_privacy: 'amounts',
    digest_daily: true,
    digest_daily_time: '18:30',
    digest_weekly: true,
    app_url: null,
    home_assistant_url: 'http://ha.local:8123',
    home_assistant_service: 'mobile_app_phone',
    ntfy_url: null,
    ntfy_topic: null,
    home_assistant_token: '••••3456',
    ntfy_token: null,
  }

  it('changes a routing cell without touching the saved tokens', async () => {
    const { calls } = mockApi({
      '/api/v1/settings/notifications': (request: Request) =>
        request.method === 'PUT' ? section : section,
      '/api/v1/notifications/deliveries': [],
    })
    renderAt(<NotificationsTab />)
    const cell = await screen.findByLabelText('High to ntfy')
    expect(cell).toBeChecked()
    await userEvent.click(cell)
    await userEvent.click(screen.getByRole('button', { name: 'Save routing' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PUT')).toBe(true))
    const body = calls.find((c) => c.method === 'PUT')?.body as Record<string, unknown>
    expect((body.routing as Record<string, string[]>).high).toEqual(['home_assistant'])
    expect(body.home_assistant_token).toBeNull() // null keeps the saved token
  })

  it('sends a test and shows the channel error, and lists failed deliveries', async () => {
    mockApi({
      '/api/v1/settings/notifications': section,
      '/api/v1/notifications/deliveries': [
        delivery({
          channel: 'ntfy',
          status: 'failed',
          attempts: 3,
          last_error: 'ntfy answered HTTP 502.',
        }),
      ],
      'POST /api/v1/notifications/test/home_assistant': { ok: true, error: null },
      'POST /api/v1/notifications/test/ntfy': {
        ok: false,
        error: 'Not set up: save the address and token first.',
      },
    })
    renderAt(<NotificationsTab />)
    await userEvent.click(
      await screen.findByRole('button', { name: 'Send a test to Home Assistant' }),
    )
    expect(await screen.findByText(/Check your phone/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Send a test to ntfy' }))
    expect(
      await screen.findByText('Not set up: save the address and token first.'),
    ).toBeInTheDocument()
    const log = screen.getByRole('table', { name: 'Delivery log' })
    expect(log).toHaveTextContent('Failed')
    expect(log).toHaveTextContent('ntfy answered HTTP 502.')
  })
})

describe('price alerts (FR-INS-05)', () => {
  it('lists the alerts with their state and adds one', async () => {
    const { calls } = mockApi({
      '/api/v1/price-alerts': (request: Request) =>
        request.method === 'POST'
          ? {}
          : [
              {
                id: 1,
                instrument_id: 5,
                instrument_name: 'Watched Co',
                currency: 'USD',
                condition: 'above',
                threshold: '110',
                note: 'take a look',
                active: true,
                armed: false,
                last_fired_at: '2026-10-05T08:00:00Z',
                last_close: '112',
                met_now: true,
              },
            ],
    })
    renderAt(<PriceAlerts instrumentId={5} name="Watched Co" />)
    expect(await screen.findByText(/Above 110 USD/)).toBeInTheDocument()
    expect(screen.getByText(/Fired; waiting/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Add alert' }))
    expect(await screen.findByText('Enter a price above zero.')).toBeInTheDocument()
    await userEvent.selectOptions(screen.getByLabelText('When it closes'), 'below')
    await userEvent.type(screen.getByLabelText('Price'), '95,5')
    await userEvent.click(screen.getByRole('button', { name: 'Add alert' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({
      instrument_id: 5,
      condition: 'below',
      threshold: '95.5',
      note: null,
    })
  })
})

describe('macro (FR-MD-08)', () => {
  it('draws each series in its own pane and reads as a table', async () => {
    mockApi({ '/api/v1/settings/general': GENERAL_US })
    renderAt(
      <MacroWidget
        data={{
          panes: [
            {
              code: 'DFII10',
              name: 'US 10-year real yield',
              unit: 'percent',
              points: [
                { date: '2024-06-13', value: '2.30' },
                { date: '2024-06-14', value: '2.34' },
              ],
            },
            {
              code: 'DTWEXBGS',
              name: 'Trade-weighted US dollar (broad)',
              unit: 'index',
              points: [{ date: '2024-06-14', value: '123.00' }],
            },
          ],
        }}
        config={{}}
        filters={{}}
      />,
    )
    expect(screen.getByText('US 10-year real yield (%)')).toBeInTheDocument()
    expect(screen.getByText('Trade-weighted US dollar (broad)')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Show data as a table' }))
    const table = screen.getByRole('table', { name: 'Macro overlay' })
    expect(within(table).getByText('2024-06-14').closest('tr')).toHaveTextContent(
      /2[.,]34.*123[.,]00/,
    )
  })

  it('lists the stored series and fetches on request', async () => {
    const { calls } = mockApi({
      '/api/v1/macro/series': [
        {
          code: 'DFII10',
          name: 'US 10-year real yield',
          source: 'fred',
          unit: 'percent',
          points: 32,
          last_date: '2024-06-14',
          last_value: '2.34',
          configured: true,
        },
      ],
      '/api/v1/settings/macro': { series: [] },
      'POST /api/v1/macro/refresh': { status: 'queued' },
    })
    renderAt(<MacroTab />)
    const row = (await screen.findByText('US 10-year real yield')).closest('tr') as HTMLElement
    expect(row).toHaveTextContent('2.34 (2024-06-14)')
    await userEvent.click(screen.getByRole('button', { name: 'Fetch now' }))
    expect(await screen.findByText('Fetching within a few seconds.')).toBeInTheDocument()
    expect(calls.some((c) => c.path === '/api/v1/macro/refresh')).toBe(true)
  })
})

describe('system information (FR-SY-10)', () => {
  it('shows version, build, disk use, the agent and failed jobs', async () => {
    mockApi({
      '/api/v1/system/info': {
        version: '0.1.0',
        build: 'abc1234def5678',
        disk: {
          database_bytes: 5 * 1024 * 1024,
          backups_bytes: 20 * 1024 * 1024,
          backups: 3,
          free_bytes: 10 * 1024 ** 3,
          total_bytes: 50 * 1024 ** 3,
        },
        agent: {
          runs_this_month: 0,
          cost_this_month_eur: '0.00',
          budget_eur: '5',
          note: 'Add your Anthropic API key under Settings, Agent to switch the agent on.',
        },
        failed_jobs_24h: 1,
        failing_news_sources: ['ECB press releases'],
      },
    })
    renderAt(<SystemInfo />)
    expect(await screen.findByText('0.1.0')).toBeInTheDocument()
    expect(screen.getByText('(abc1234def56)')).toBeInTheDocument()
    expect(screen.getByText('5.0 MB')).toBeInTheDocument()
    expect(screen.getByText('3 files, 20.0 MB')).toBeInTheDocument()
    expect(screen.getByText('0 runs, 0.00 of 5 EUR')).toBeInTheDocument()
    expect(screen.getByText('1')).toHaveClass('text-danger')
    expect(screen.getByText(/Add your Anthropic API key/)).toBeInTheDocument()
    expect(screen.getByText('ECB press releases')).toHaveClass('text-danger') // a failing source
  })
})
