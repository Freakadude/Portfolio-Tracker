import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ExposurePart } from './dashboards/types'
import { AllocationWidget } from './dashboards/widgets/Composition'
import { LookThroughWidget } from './dashboards/widgets/LookThrough'
import { HoldingsPanel } from './lookthrough/HoldingsPanel'
import { NewsTab } from './news/NewsTab'
import { News } from './pages/News'
import { GENERAL_US, mockApi, problem, renderAt } from './test-utils'

afterEach(() => vi.unstubAllGlobals())

// --- an ETF's holdings (FR-MD-09) --------------------------------------------------------------

const VIEW = {
  snapshots: [
    {
      id: 4,
      as_of: '2026-10-03',
      source: 'csv',
      file_name: 'x.csv',
      covered_pct: '99.5',
      holdings: 3,
      stale: false,
    },
    {
      id: 3,
      as_of: '2026-07-01',
      source: 'url',
      file_name: null,
      covered_pct: '99.0',
      holdings: 3,
      stale: true,
    },
  ],
  top: [
    {
      name: 'ALPHA TECH INC',
      isin: null,
      ticker: 'AAA',
      weight_pct: '40.00',
      sector: 'Information Technology',
      country: 'United States',
      currency: 'USD',
    },
    {
      name: 'BETA BANK PLC',
      isin: null,
      ticker: 'BBB',
      weight_pct: '30.50',
      sector: 'Financials',
      country: 'United Kingdom',
      currency: 'GBP',
    },
  ],
  source: { url: null, eodhd: false },
  stale_days: 45,
}
const MAPPING = {
  header_row: 9,
  name: 1,
  weight: 5,
  isin: null,
  ticker: 0,
  sector: 2,
  country: 9,
  currency: 11,
  kind: 3,
  weight_is_fraction: false,
  decimal_separator: '.',
  thousands_separator: '',
}
const PREVIEW = {
  sheets: [] as { name: string; holdings: number }[],
  headers: [
    { index: 0, label: 'Ticker' },
    { index: 1, label: 'Name' },
    { index: 5, label: 'Weight (%)' },
  ],
  mapping: MAPPING,
  as_of: '2026-10-03',
  holdings: 3,
  covered_pct: '99.50',
  top: VIEW.top,
  dropped: ['USD CASH: 0.4 %'],
  warnings: [],
  errors: [],
}
const HOLDINGS = '/api/v1/instruments/7/holdings'

async function pick(file = new File(['x'], 'holdings.csv', { type: 'text/csv' })) {
  await userEvent.upload(screen.getByLabelText('Holdings file (CSV, Excel or PDF)'), file)
}

describe('a workbook with several sheets', () => {
  const SHEETS = [
    { name: 'Cover', holdings: 0 },
    { name: 'Holdings', holdings: 3 },
  ]

  it('offers the sheets and reads the one that is chosen with its own columns', async () => {
    const bodies: string[] = []
    mockApi({
      [`GET ${HOLDINGS}`]: { ...VIEW, snapshots: [], top: [] },
      [`POST ${HOLDINGS}/preview`]: async (request: Request) => {
        const text = await request.text() // the form as sent: parts named "sheet", "mapping"...
        bodies.push(text)
        const sheet = /name="sheet"\s+(\S+)/.exec(text)?.[1] ?? 'Holdings'
        return {
          ...PREVIEW,
          sheets: SHEETS,
          mapping: { ...MAPPING, sheet },
          holdings: sheet === 'Holdings' ? 3 : 0,
        }
      },
    })
    renderAt(<HoldingsPanel instrumentId={7} />)
    await screen.findByText('No holdings yet. Upload a file below.')
    expect(screen.queryByLabelText('Sheet')).toBeNull() // nothing to choose before a file is read
    await pick(new File(['x'], 'holdings.xlsx'))
    await userEvent.click(screen.getByRole('button', { name: 'Preview' }))
    const sheet = await screen.findByLabelText('Sheet')
    expect(sheet).toHaveValue('Holdings') // the one with the holdings is suggested
    expect(screen.getByRole('option', { name: 'Cover (0 holdings)' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Holdings (3 holdings)' })).toBeInTheDocument()

    await userEvent.selectOptions(sheet, 'Cover')
    await waitFor(() => expect(bodies).toHaveLength(2))
    expect(bodies[1]).toMatch(/name="sheet"\s+Cover/)
    expect(bodies[1]).not.toContain('name="mapping"') // the columns are suggested again
    await waitFor(() => expect(screen.getByLabelText('Sheet')).toHaveValue('Cover'))
  })

  it('shows no sheet choice for a file with one sheet', async () => {
    mockApi({
      [`GET ${HOLDINGS}`]: { ...VIEW, snapshots: [], top: [] },
      [`POST ${HOLDINGS}/preview`]: PREVIEW,
    })
    renderAt(<HoldingsPanel instrumentId={7} />)
    await screen.findByText('No holdings yet. Upload a file below.')
    await pick()
    await userEvent.click(screen.getByRole('button', { name: 'Preview' }))
    await screen.findByText(/Read as: 3 holdings/)
    expect(screen.queryByLabelText('Sheet')).toBeNull()
  })
})

describe('what a fund holds (FR-MD-09)', () => {
  it('lists the saved holdings, calls out an old snapshot and shows the largest holdings', async () => {
    mockApi({ [`GET ${HOLDINGS}`]: VIEW })
    renderAt(<HoldingsPanel instrumentId={7} />)
    const table = await screen.findByRole('table', { name: 'Saved holdings' })
    expect(within(table).getByText('Out of date')).toBeInTheDocument() // the July file
    expect(within(table).getByText('Uploaded file')).toBeInTheDocument()
    expect(within(table).getByText('99.5 % of the fund')).toBeInTheDocument()
    const top = screen.getByRole('table', { name: 'Largest holdings' })
    expect(within(top).getByText('ALPHA TECH INC')).toBeInTheDocument()
    expect(within(top).getByText('40.00')).toBeInTheDocument()
  })

  it('asks for a file first, previews it, and saves it once the owner is happy', async () => {
    const { calls } = mockApi({
      [`GET ${HOLDINGS}`]: { ...VIEW, snapshots: [], top: [] },
      [`POST ${HOLDINGS}/preview`]: PREVIEW,
      [`POST ${HOLDINGS}`]: new Response(
        JSON.stringify({ snapshot: { ...VIEW.snapshots[0], holdings: 3 }, warnings: [] }),
        { status: 201, headers: { 'content-type': 'application/json' } },
      ),
    })
    renderAt(<HoldingsPanel instrumentId={7} />)
    expect(await screen.findByText('No holdings yet. Upload a file below.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Preview' }))
    expect(await screen.findByText('Choose a CSV, Excel or PDF file first.')).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'POST')).toBe(false)

    await pick()
    await userEvent.click(screen.getByRole('button', { name: 'Preview' }))
    expect(
      await screen.findByText('Read as: 3 holdings, 99.5 % of the fund, dated 2026-10-03.'),
    ).toBeInTheDocument()
    expect(screen.getByText('Left out (cash and derivatives): USD CASH: 0.4 %')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Save these holdings' }))
    expect(await screen.findByText('Saved 3 holdings from 2026-10-03.')).toBeInTheDocument()
    const stored = calls.filter((c) => c.method === 'POST' && c.path === HOLDINGS)
    expect(stored).toHaveLength(1)
  })

  it('lets the owner correct the column match and read the file again', async () => {
    const { calls } = mockApi({
      [`GET ${HOLDINGS}`]: { ...VIEW, snapshots: [], top: [] },
      [`POST ${HOLDINGS}/preview`]: PREVIEW,
    })
    renderAt(<HoldingsPanel instrumentId={7} />)
    await screen.findByText('No holdings yet. Upload a file below.')
    await pick()
    await userEvent.click(screen.getByRole('button', { name: 'Preview' }))
    await screen.findByText(/Read as:/)
    await userEvent.selectOptions(screen.getByLabelText('Weight'), '0')
    await userEvent.click(screen.getByRole('button', { name: 'Read again' }))
    await waitFor(() =>
      expect(calls.filter((c) => c.path === `${HOLDINGS}/preview`)).toHaveLength(2),
    )
    const second = calls.filter((c) => c.path === `${HOLDINGS}/preview`)[1].body as string
    expect(second).toContain('name="mapping"')
    expect(second).toContain('"weight":0')
  })

  it('explains a file that cannot be read and does not offer to save it', async () => {
    mockApi({
      [`GET ${HOLDINGS}`]: { ...VIEW, snapshots: [], top: [] },
      [`POST ${HOLDINGS}/preview`]: problem(
        422,
        'Holdings problem',
        'No column of weights that adds up to 100 % was found.',
      ),
    })
    renderAt(<HoldingsPanel instrumentId={7} />)
    await screen.findByText('No holdings yet. Upload a file below.')
    await pick()
    await userEvent.click(screen.getByRole('button', { name: 'Preview' }))
    expect(await screen.findByText(/No column of weights/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Save these holdings' })).not.toBeInTheDocument()
  })

  it('saves where the holdings are refreshed from and can ask for a refresh now', async () => {
    const { calls } = mockApi({
      [`GET ${HOLDINGS}`]: {
        ...VIEW,
        source: { url: 'https://issuer.example/h.csv', eodhd: false },
      },
      [`PUT ${HOLDINGS}/source`]: { url: 'https://issuer.example/h2.csv', eodhd: true },
      [`POST ${HOLDINGS}/refresh`]: new Response(JSON.stringify({ status: 'queued' }), {
        status: 202,
      }),
    })
    renderAt(<HoldingsPanel instrumentId={7} />)
    const url = await screen.findByLabelText("Issuer's download address (CSV, Excel or PDF)")
    expect(url).toHaveValue('https://issuer.example/h.csv')
    await userEvent.clear(url)
    await userEvent.type(url, 'https://issuer.example/h2.csv')
    await userEvent.click(screen.getByLabelText('Use EODHD fundamentals'))
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({
        url: 'https://issuer.example/h2.csv',
        eodhd: true,
      }),
    )
    await userEvent.click(screen.getByRole('button', { name: 'Refresh now' }))
    expect(await screen.findByText(/Asked the worker to refresh/)).toBeInTheDocument()
  })
})

// --- the look-through widgets (FR-PF-05) ---------------------------------------------------------

const PARTS: ExposurePart[] = [
  { source: 'Alpha Inc', instrument_id: 2, kind: 'direct', value_eur: '1080', weight_pct: null },
  {
    source: 'F fund',
    instrument_id: 1,
    kind: 'look_through',
    value_eur: '118.8',
    weight_pct: '10',
  },
]

describe('look-through on dashboards', () => {
  it('shows the largest exposures, where each one sits, and opens the position that holds it', async () => {
    mockApi({ '/api/v1/settings/general': GENERAL_US })
    const { container } = renderAt(
      <LookThroughWidget
        data={{
          dimension: 'company',
          total_eur: '2808',
          slices: [
            {
              key: 'Alpha Inc',
              value_eur: '1306.8',
              weight: '0.4653846',
              other: false,
              parts: PARTS,
            },
            {
              key: 'Other holdings of F fund',
              value_eur: '356.4',
              weight: '0.1269',
              other: true,
              parts: [],
            },
          ],
          rest_weight: '0.2',
          opened: [{ name: 'F fund', holdings_as_of: '2024-01-05' }],
          unopened: ['World ETF'],
        }}
        config={{}}
        filters={{}}
      />,
    )
    expect(screen.getByText('Alpha Inc')).toBeInTheDocument()
    expect(await screen.findByText(/46[.,]5/)).toBeInTheDocument()
    expect(screen.getByText('Opened up: F fund (2024-01-05).')).toBeInTheDocument()
    expect(
      screen.getByText('Shown as themselves, holdings not loaded: World ETF.'),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Other holdings of F fund/ })).toBeDisabled() // no company
    await userEvent.click(screen.getByRole('button', { name: 'Show data as a table' }))
    expect(screen.getByText(/Alpha Inc: held directly, .*1,080/)).toBeInTheDocument()
    expect(screen.getByText(/F fund: 10\.0 % of the fund, .*119/)).toBeInTheDocument()
    expect(container.querySelector('table')).not.toBeNull()
  })

  it('says why there is nothing to show', () => {
    mockApi({ '/api/v1/settings/general': GENERAL_US })
    renderAt(
      <LookThroughWidget
        data={{
          empty: true,
          reason:
            'None of your ETFs has its holdings yet. Open an ETF under Holdings and upload its holdings file.',
        }}
        config={{}}
        filters={{}}
      />,
    )
    expect(screen.getByText(/None of your ETFs has its holdings yet/)).toBeInTheDocument()
  })

  it('the allocation widget explains a look-through exposure in its table view', async () => {
    mockApi({ '/api/v1/settings/general': GENERAL_US })
    renderAt(
      <AllocationWidget
        data={{
          group_by: 'company',
          chart: 'donut',
          show_target: false,
          look_through: true,
          total_eur: '2808',
          unvalued: 0,
          unopened: ['World ETF'],
          slices: [
            {
              key: 'Alpha Inc',
              value_eur: '1306.8',
              weight: '0.4653846',
              target: null,
              drift_pp: null,
              outside_band: null,
              parts: PARTS,
            },
          ],
        }}
        config={{}}
        filters={{}}
      />,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Show data as a table' }))
    expect(screen.getByRole('columnheader', { name: 'Where it sits' })).toBeInTheDocument()
    expect(screen.getByText(/Alpha Inc: held directly, .*1,080/)).toBeInTheDocument()
    expect(
      screen.getByText('Shown as themselves, holdings not loaded: World ETF.'),
    ).toBeInTheDocument()
  })
})

// --- the News page (FR-NW-07, FR-NW-08) ----------------------------------------------------------

const STORY = {
  id: 11,
  title: 'ASML raises outlook on strong chip orders',
  first_seen: '2026-10-05T07:00:00Z',
  last_seen: '2026-10-05T09:00:00Z',
  relevance: '0.8',
  items: [
    {
      id: 1,
      source: 'ECB press releases',
      title: 'ASML raises outlook',
      summary: '',
      url: 'https://ecb.europa.eu/a',
      published: '2026-10-05T07:00:00Z',
    },
    {
      id: 2,
      source: 'EODHD news for your tickers',
      title: 'ASML lifts guidance',
      summary: '',
      url: 'https://news.example/b',
      published: '2026-10-05T09:00:00Z',
    },
  ],
  links: [
    {
      id: 5,
      link_type: 'direct',
      instrument_id: 2,
      sleeve: null,
      label: 'ASML Holding',
      weight_pct: null,
      relevance: '0.8',
      matched_by: 'alias:asml',
    },
    {
      id: 6,
      link_type: 'look_through',
      instrument_id: 1,
      sleeve: null,
      label: 'World ETF',
      weight_pct: '0.8',
      relevance: '0.1',
      matched_by: 'constituent:asml',
    },
  ],
  assessment: {
    impact_score: 72,
    direction: 'positive',
    horizon: 'weeks',
    affected: ['ASML Holding'],
    rationale: 'Raised guidance on strong orders. It lifts the direct holding most.',
    confidence: 'medium',
    model: 'claude-sonnet-5-5',
  },
}
const NEWS_ROUTES = {
  '/api/v1/instruments': [
    { id: 1, name: 'World ETF', listings: [], tags: [] },
    { id: 2, name: 'ASML Holding', listings: [], tags: [] },
  ],
  '/api/v1/news/sources': [
    {
      id: 3,
      name: 'ECB press releases',
      kind: 'rss',
      url: 'https://www.ecb.europa.eu/rss/press.html',
      language: 'en',
      trust_weight: '1',
      poll_minutes: 60,
      enabled: true,
      macro_series: ['ECB_DFR'],
      items: 15,
      last_fetch_at: '2026-10-05T09:00:00Z',
      next_fetch_at: null,
      failures: 0,
      last_error: null,
    },
  ],
}

describe('the News page', () => {
  it('shows a story with its assessment, what it is linked to and where it was reported', async () => {
    mockApi({ ...NEWS_ROUTES, '/api/v1/news': { clusters: [STORY], total: 1 } })
    renderAt(<News />)
    const card = await screen.findByRole('article', { name: STORY.title })
    expect(within(card).getByText('Impact 72')).toBeInTheDocument()
    expect(within(card).getByText('Positive')).toBeInTheDocument()
    expect(within(card).getByText(/Raised guidance on strong orders/)).toBeInTheDocument()
    expect(within(card).getByText('ASML Holding · directly')).toBeInTheDocument()
    expect(
      within(card).getByText('World ETF · inside the fund · 0.8 % of the fund'),
    ).toBeInTheDocument()
    expect(within(card).getByText('Reported by 2 sources.')).toBeInTheDocument()
    const link = within(card).getByRole('link', { name: 'ASML raises outlook' })
    expect(link).toHaveAttribute('href', 'https://ecb.europa.eu/a')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer') // news copy is never rendered as markup
  })

  it('asks the API for what the filters say', async () => {
    const { calls } = mockApi({ ...NEWS_ROUTES, '/api/v1/news': { clusters: [], total: 0 } })
    renderAt(<News />)
    expect(await screen.findByText('No news yet')).toBeInTheDocument()
    await userEvent.selectOptions(screen.getByLabelText('Holding'), '1')
    await userEvent.selectOptions(screen.getByLabelText('Impact'), '50')
    await userEvent.selectOptions(screen.getByLabelText('Direction'), 'negative')
    await userEvent.selectOptions(screen.getByLabelText('Order'), 'impact')
    await userEvent.click(screen.getByLabelText('Show stories linked to nothing'))
    await waitFor(() => {
      const last = calls.filter((c) => c.path === '/api/v1/news').at(-1)
      expect(last).toBeDefined()
    })
    const urls = calls.filter((c) => c.path === '/api/v1/news')
    expect(urls.length).toBeGreaterThanOrEqual(5)
  })

  it('marks a story not relevant and says what that changed', async () => {
    const { calls } = mockApi({
      ...NEWS_ROUTES,
      '/api/v1/news': { clusters: [STORY], total: 1 },
      'POST /api/v1/news/clusters/11/feedback': {
        changes: [{ kind: 'source_trust', name: 'ECB press releases', old: '1', new: '0.9' }],
      },
    })
    renderAt(<News />)
    await userEvent.click(
      await screen.findByRole('button', { name: `Not relevant: ${STORY.title}` }),
    )
    expect(
      await screen.findByText('Trust in ECB press releases went from 1 to 0.9.'),
    ).toBeInTheDocument()
    expect(calls.find((c) => c.path.endsWith('/feedback'))?.body).toEqual({
      verdict: 'not_relevant',
      link_id: null,
    })
  })

  it('marks one wrong link, which only lowers the alias that found it', async () => {
    const { calls } = mockApi({
      ...NEWS_ROUTES,
      '/api/v1/news': { clusters: [STORY], total: 1 },
      'POST /api/v1/news/clusters/11/feedback': {
        changes: [{ kind: 'alias_weight', name: 'asml', old: '1', new: '0.8' }],
      },
    })
    renderAt(<News />)
    await userEvent.click(
      await screen.findByRole('button', { name: 'This link to ASML Holding is wrong' }),
    )
    expect(
      await screen.findByText('The name "asml" now counts for 0.8 when matching stories.'),
    ).toBeInTheDocument()
    expect(calls.find((c) => c.path.endsWith('/feedback'))?.body).toEqual({
      verdict: 'not_relevant',
      link_id: 5,
    })
    expect(
      screen.queryByRole('button', { name: 'This link to World ETF is wrong' }),
    ).not.toBeInTheDocument() // not an alias match
  })
})

// --- Settings, News (FR-NW-01, FR-NW-02) ----------------------------------------------------------

describe('news sources', () => {
  it('lists the sources with their status and a failing one with its error', async () => {
    mockApi({
      '/api/v1/news/sources': [
        ...NEWS_ROUTES['/api/v1/news/sources'],
        {
          id: 4,
          name: 'Issuer notices',
          kind: 'rss',
          url: 'https://issuer.example/f.xml',
          language: 'en',
          trust_weight: '0.7',
          poll_minutes: 120,
          enabled: false,
          macro_series: [],
          items: 0,
          last_fetch_at: null,
          next_fetch_at: null,
          failures: 3,
          last_error: 'The feed address was not found (HTTP 404). Check the address.',
        },
      ],
      '/api/v1/settings/news': { triage: true, batch_size: 8 },
    })
    renderAt(<NewsTab />)
    await screen.findByText('Working')
    const table = screen.getByRole('table', { name: 'News sources' })
    expect(within(table).getByText('Working')).toBeInTheDocument()
    expect(within(table).getByText('Failing (3)')).toBeInTheDocument()
    expect(within(table).getByText(/The feed address was not found/)).toBeInTheDocument()
    expect(within(table).getByText('15 stories stored')).toBeInTheDocument()
    expect(within(table).getByText('(off)')).toBeInTheDocument()
  })

  it('previews a feed before it is saved, then adds it', async () => {
    const { calls } = mockApi({
      '/api/v1/news/sources': [],
      '/api/v1/settings/news': { triage: true },
      'POST /api/v1/news/sources/preview': {
        items: [
          {
            title: 'Index change for the semis fund',
            summary: '',
            url: 'https://i.example/1',
            published: '2026-10-02T09:00:00Z',
          },
        ],
        total: 15,
      },
      'POST /api/v1/news/sources': new Response(JSON.stringify({ id: 9 }), {
        status: 201,
        headers: { 'content-type': 'application/json' },
      }),
    })
    renderAt(<NewsTab />)
    await userEvent.click(await screen.findByRole('button', { name: 'Add a source' }))
    await userEvent.type(screen.getByLabelText('Name'), 'Issuer notices')
    await userEvent.type(screen.getByLabelText('Feed address'), 'https://issuer.example/feed.xml')
    await userEvent.click(screen.getByRole('button', { name: 'Preview' }))
    expect(await screen.findByText('The latest 1 of 15 items in this feed:')).toBeInTheDocument()
    expect(screen.getByText(/Index change for the semis fund/)).toBeInTheDocument()
    expect(calls.find((c) => c.path.endsWith('/preview'))?.body).toEqual({
      url: 'https://issuer.example/feed.xml',
    })
    await userEvent.click(screen.getAllByRole('button', { name: 'Save' })[0])
    await waitFor(() => {
      const made = calls.find((c) => c.method === 'POST' && c.path === '/api/v1/news/sources')
      expect(made?.body).toMatchObject({
        name: 'Issuer notices',
        url: 'https://issuer.example/feed.xml',
        enabled: true,
      })
    })
  })

  it('shows why a feed cannot be previewed', async () => {
    mockApi({
      '/api/v1/news/sources': [],
      '/api/v1/settings/news': { triage: true },
      'POST /api/v1/news/sources/preview': problem(
        422,
        'Cannot read feed',
        'That address does not return an RSS or Atom feed.',
      ),
    })
    renderAt(<NewsTab />)
    await userEvent.click(await screen.findByRole('button', { name: 'Add a source' }))
    await userEvent.type(screen.getByLabelText('Feed address'), 'https://issuer.example/page')
    await userEvent.click(screen.getByRole('button', { name: 'Preview' }))
    expect(
      await screen.findByText('That address does not return an RSS or Atom feed.'),
    ).toBeInTheDocument()
  })

  it('deletes a source after confirmation and can ask for a fetch now', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const { calls } = mockApi({
      ...NEWS_ROUTES,
      '/api/v1/settings/news': { triage: true },
      'DELETE /api/v1/news/sources/3': new Response(null, { status: 204 }),
      'POST /api/v1/news/sources/3/fetch': new Response(JSON.stringify({ status: 'queued' }), {
        status: 202,
      }),
    })
    renderAt(<NewsTab />)
    await userEvent.click(
      await screen.findByRole('button', { name: 'Fetch now ECB press releases' }),
    )
    expect(await screen.findByText(/Asked the worker to fetch/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Delete ECB press releases' }))
    await waitFor(() =>
      expect(calls.some((c) => c.method === 'DELETE' && c.path.endsWith('/3'))).toBe(true),
    )
  })
})
