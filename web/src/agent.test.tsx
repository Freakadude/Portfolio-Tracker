import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AgentTab } from './agent/AgentTab'
import { Recommendations } from './agent/Recommendations'
import { RunsPanel } from './agent/RunsPanel'
import { NewsFeedWidget, SignalsWidget } from './dashboards/widgets/Feeds'
import { GENERAL_US, mockApi, problem, renderAt } from './test-utils'

afterEach(() => vi.unstubAllGlobals())

const REC = {
  id: 7,
  run_id: 1,
  created_at: '2026-10-14T17:30:00Z',
  action_type: 'direct_contribution',
  severity: 'medium',
  subjects: ['gold_hedge'],
  title: 'Direct new money to gold_hedge',
  summary: 'gold_hedge is 20.0 pp under its 60% target; buy 10 units of Gold ETC.',
  rationale: 'The drift rule fired (signal 1) and the allocator orders 10 units.',
  calculation_id: 1,
  evidence: [
    { kind: 'signal', ref: '1', note: 'Drift signal' },
    { kind: 'news_cluster', ref: '5', note: 'Fed statement' },
    { kind: 'web_source', ref: 'https://www.ecb.europa.eu/press/x.html', note: 'ECB page' },
  ],
  sources: ['https://www.ecb.europa.eu/press/x.html'],
  confidence: 'medium',
  departs_from_principles: null,
  what_would_change_this: 'A rally in gold before the order is placed.',
  expires_at: '2026-10-28T17:30:00Z',
  status: 'new',
  user_note: null,
  snoozed_until: null,
  linked_transaction_ids: [],
  ai_label: 'AI-generated, not financial advice.',
}
const DETAIL = {
  ...REC,
  orders: [
    {
      side: 'buy',
      sleeve: 'gold_hedge',
      instrument_id: 3,
      name: 'Gold ETC',
      quantity: '10',
      price: '100',
      currency: 'EUR',
      amount_eur: '1000',
    },
  ],
  remainder_eur: '0',
  plan_current: true,
}
const BUDGET = {
  month: '2026-10',
  enabled: true,
  key_set: true,
  spent_eur: '0.42',
  budget_eur: '5',
  remaining_eur: '4.58',
  news_spent_eur: '0.10',
  news_share_eur: '1.50',
  runs_this_month: 3,
  runs_today: 1,
  daily_run_cap: 10,
  paused: false,
}
const BASE = {
  '/api/v1/settings/general': GENERAL_US,
  '/api/v1/agent/usage': BUDGET,
  'GET /api/v1/recommendations': [REC],
  'GET /api/v1/recommendations/7': DETAIL,
}

describe('recommendations on Insights (FR-AG-05)', () => {
  it('shows an item with its label, calculation, evidence and the buttons to decide', async () => {
    mockApi(BASE)
    renderAt(<Recommendations />)
    const card = await screen.findByRole('article', { name: REC.title })
    expect(within(card).getByText('AI-generated')).toBeInTheDocument()
    expect(screen.getByText(/AI-generated, not financial advice/)).toBeInTheDocument()
    expect(within(card).getByText(/buy 10 units of Gold ETC/)).toBeInTheDocument()
    const orders = await within(card).findByRole('table', { name: 'Orders from the calculator' })
    expect(within(orders).getByText('Gold ETC')).toBeInTheDocument()
    expect(within(card).queryByText('Departs from your principles')).not.toBeInTheDocument()
    expect(screen.getByText('AI cost this month: 0.42 of 5 EUR.')).toBeInTheDocument()
    const link = within(card).getByRole('link', { name: 'Open in What-if' })
    expect(decodeURIComponent(link.getAttribute('href') ?? '')).toContain(
      '"instrument_id":3,"side":"buy","quantity":"10"',
    )
    expect(within(card).getByRole('link', { name: 'Open the story' })).toHaveAttribute(
      'href',
      '/news?cluster=5',
    )
  })

  it('marks advice that departs from the principles with its own badge and the reason', async () => {
    mockApi({
      ...BASE,
      'GET /api/v1/recommendations': [
        {
          ...REC,
          departs_from_principles: 'The principles say to rebalance with new money first.',
        },
      ],
      'GET /api/v1/recommendations/7': {
        ...DETAIL,
        departs_from_principles: 'The principles say to rebalance with new money first.',
      },
    })
    renderAt(<Recommendations />)
    const card = await screen.findByRole('article', { name: REC.title })
    expect(within(card).getByText('Departs from your principles')).toBeInTheDocument()
    expect(within(card).getByText(/rebalance with new money first/)).toBeInTheDocument()
  })

  it('accepts, and can make draft transactions from the calculation', async () => {
    const { calls } = mockApi({
      ...BASE,
      'PATCH /api/v1/recommendations/7': {
        recommendation: { ...DETAIL, status: 'accepted' },
        drafts: [41],
      },
    })
    renderAt(<Recommendations />)
    await userEvent.click(
      await screen.findByRole('button', {
        name: `Accept and make draft transactions: ${REC.title}`,
      }),
    )
    expect(await screen.findByText('1 draft transaction made.')).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({
      action: 'accept',
      note: null,
      days: null,
      create_drafts: true,
    })
  })

  it('refuses drafts for an order list that is out of date and says why', async () => {
    mockApi({ ...BASE, 'GET /api/v1/recommendations/7': { ...DETAIL, plan_current: false } })
    renderAt(<Recommendations />)
    expect(await screen.findByText(/order list is out of date/)).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: `Accept and make draft transactions: ${REC.title}` }),
    ).toBeDisabled()
    expect(screen.getByRole('button', { name: `Accept: ${REC.title}` })).toBeEnabled() // record it by hand
  })

  it('rejects with an optional one-line reason', async () => {
    const { calls } = mockApi({
      ...BASE,
      'PATCH /api/v1/recommendations/7': {
        recommendation: { ...DETAIL, status: 'rejected' },
        drafts: [],
      },
    })
    renderAt(<Recommendations />)
    await userEvent.click(await screen.findByRole('button', { name: `Reject: ${REC.title}` }))
    await userEvent.type(
      screen.getByLabelText('Why? (optional, one line)'),
      'I never add to gold in March.',
    )
    await userEvent.click(screen.getByRole('button', { name: 'Reject it' }))
    await waitFor(() =>
      expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({
        action: 'reject',
        note: 'I never add to gold in March.',
        days: null,
        create_drafts: false,
      }),
    )
  })

  it('snoozes for the days chosen and can mark an item seen', async () => {
    const { calls } = mockApi({
      ...BASE,
      'PATCH /api/v1/recommendations/7': {
        recommendation: { ...DETAIL, status: 'snoozed' },
        drafts: [],
      },
    })
    renderAt(<Recommendations />)
    await userEvent.selectOptions(await screen.findByLabelText('Days to snooze'), '7')
    await userEvent.click(screen.getByRole('button', { name: `Snooze: ${REC.title}` }))
    await waitFor(() =>
      expect(calls.find((c) => c.method === 'PATCH')?.body).toMatchObject({
        action: 'snooze',
        days: 7,
      }),
    )
    await userEvent.click(screen.getByRole('button', { name: `Mark as seen: ${REC.title}` }))
    await waitFor(() => expect(calls.filter((c) => c.method === 'PATCH')).toHaveLength(2))
  })

  it('shows a refused decision from the server', async () => {
    mockApi({
      ...BASE,
      'PATCH /api/v1/recommendations/7': problem(
        409,
        'Cannot record the decision',
        'This recommendation is expired and can no longer be changed.',
      ),
    })
    renderAt(<Recommendations />)
    await userEvent.click(await screen.findByRole('button', { name: `Accept: ${REC.title}` }))
    expect(await screen.findByText(/can no longer be changed/)).toBeInTheDocument()
  })

  it("shows past decisions with the owner's reason, and asks the worker for a review", async () => {
    const { calls } = mockApi({
      ...BASE,
      'GET /api/v1/recommendations': (request: Request) =>
        new URL(request.url).searchParams.get('status') === 'rejected'
          ? [{ ...REC, status: 'rejected', user_note: 'I never add to gold in March.' }]
          : [],
      'POST /api/v1/agent/runs': new Response(JSON.stringify({ status: 'queued' }), {
        status: 202,
      }),
    })
    renderAt(<Recommendations />)
    expect(await screen.findByText('Nothing is waiting for a decision.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Run a review now' }))
    expect(await screen.findByText(/Asking the worker to start/)).toBeInTheDocument()
    expect(calls.find((c) => c.path === '/api/v1/agent/runs')?.body).toEqual({
      run_type: 'daily_review',
      question: null,
    })
    await userEvent.selectOptions(screen.getByLabelText('Show'), 'rejected')
    expect(
      await screen.findByText('Your reason: I never add to gold in March.'),
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Accept/ })).not.toBeInTheDocument() // decided: no buttons
  })

  it('says why nothing runs without a key, and pauses the button when the agent is off', async () => {
    mockApi({
      ...BASE,
      '/api/v1/agent/usage': { ...BUDGET, key_set: false, enabled: false },
      'GET /api/v1/recommendations': [],
    })
    renderAt(<Recommendations />)
    expect(await screen.findByText(/Add your Anthropic API key/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Run a review now' })).toBeDisabled()
  })
})

describe('Settings, Agent (FR-AG-09)', () => {
  it('shows the month against the budget and tests the key', async () => {
    mockApi({
      ...BASE,
      '/api/v1/settings/agent': {
        enabled: true,
        monthly_budget_eur: '5',
        anthropic_api_key: '••••1234',
      },
      'POST /api/v1/agent/test': {
        ok: true,
        model: 'claude-haiku-4-5-20251001',
        reply: 'ok',
        cost_eur: '0.00003',
      },
    })
    renderAt(<AgentTab />)
    expect(await screen.findByText('0.42 of 5 EUR (4.58 left)')).toBeInTheDocument()
    expect(screen.getByText('0.10 of 1.50 EUR')).toBeInTheDocument()
    expect(screen.getByText('3 this month, 1 today (cap 10 a day)')).toBeInTheDocument()
    expect(screen.getByText('On')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Test the key' }))
    expect(
      await screen.findByText(
        'The key works (claude-haiku-4-5-20251001). The test cost 0.00003 EUR.',
      ),
    ).toBeInTheDocument()
  })

  it('cannot test a key that is not saved and says what state the agent is in', async () => {
    mockApi({
      ...BASE,
      '/api/v1/agent/usage': { ...BUDGET, key_set: false },
      '/api/v1/settings/agent': { enabled: true },
    })
    renderAt(<AgentTab />)
    expect(await screen.findByText('Waiting for an API key')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Test the key' })).toBeDisabled()
  })
})

describe('the agent run list and its trace', () => {
  const RUN = {
    id: 1,
    trigger: 'daily',
    run_type: 'daily_review',
    model: 'claude-sonnet-5-5',
    prompt_version: 'system@1+ab12cd34, investigate@1+11111111, compose@1+22222222',
    status: 'ok',
    error: null,
    started_at: '2026-10-14T17:30:00Z',
    finished_at: '2026-10-14T17:31:00Z',
    input_tokens: 4300,
    output_tokens: 650,
    cache_read_tokens: 1500,
    cache_write_tokens: 0,
    web_searches: 1,
    cost_eur: '0.0213',
    digest: 'Gold is under its target.',
    recommendations: 1,
    refused: 1,
  }
  const DETAIL_RUN = {
    ...RUN,
    context: { run: { type: 'daily_review' } },
    tool_calls: [
      { name: 'get_signals', input: { state: 'open' }, error: false },
      { name: 'run_calculator', input: { kind: 'allocator' }, error: false },
      { name: 'get_positions', input: {}, error: true },
    ],
    findings: 'gold_hedge is under target (signal 1).',
    output: {
      text: '{"digest":"x"}',
      verdicts: [
        { index: 0, accepted: true, reasons: [] },
        { index: 1, accepted: false, reasons: ['a trade needs a calculation from this run'] },
      ],
    },
    items: [
      {
        id: 7,
        action_type: 'direct_contribution',
        severity: 'medium',
        subjects: [],
        title: 'Direct new money to gold_hedge',
        status: 'new',
        refused_reason: null,
      },
      {
        id: 8,
        action_type: 'trim',
        severity: 'high',
        subjects: [],
        title: 'Sell gold now',
        status: 'refused',
        refused_reason: 'a trade needs a calculation from this run',
      },
    ],
  }

  it('lists the runs with cost and what was made, and opens the whole trace', async () => {
    mockApi({
      '/api/v1/agent/runs': [
        RUN,
        {
          ...RUN,
          id: 2,
          status: 'budget',
          error: 'The AI budget for 2026-10 is used up.',
          cost_eur: '0',
          recommendations: 0,
          refused: 0,
        },
      ],
      '/api/v1/agent/runs/1': DETAIL_RUN,
    })
    renderAt(<RunsPanel />)
    const table = await screen.findByRole('table', { name: 'Agent runs' })
    expect(within(table).getByText('Done')).toBeInTheDocument()
    expect(within(table).getByText('Stopped by the budget')).toBeInTheDocument()
    expect(within(table).getByText('1 shown, 1 refused')).toBeInTheDocument()
    expect(within(table).getByText('0.0213')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Trace of run 1' }))
    const trace = await screen.findByRole('region', { name: 'Trace of run 1' })
    expect(
      within(trace).getByText('4300 tokens in, 650 out, 1500 read from the cache, 1 web searches.'),
    ).toBeInTheDocument()
    expect(within(trace).getByText(/Prompts: system@1\+ab12cd34/)).toBeInTheDocument()
    const verdicts = within(trace).getByRole('list', { name: 'Verdicts on each recommendation' })
    expect(within(verdicts).getByText('Refused')).toBeInTheDocument()
    expect(
      within(verdicts).getByText('a trade needs a calculation from this run'),
    ).toBeInTheDocument()
    expect(within(trace).getByText('Tool calls (3)')).toBeInTheDocument()
    expect(within(trace).getByText('(failed)')).toBeInTheDocument()
  })

  it('says when the agent has not run yet', async () => {
    mockApi({ '/api/v1/agent/runs': [] })
    renderAt(<RunsPanel />)
    expect(await screen.findByText('The agent has not run yet.')).toBeInTheDocument()
  })
})

describe('the news and signals widgets', () => {
  it('lists linked stories with their impact', () => {
    renderAt(
      <NewsFeedWidget
        data={{
          stories: [
            {
              id: 5,
              title: 'ASML raises outlook',
              last_seen: '2026-10-05T09:00:00Z',
              impact: 72,
              direction: 'positive',
              links: ['ASML Holding', 'World ETF'],
            },
          ],
        }}
        config={{}}
        filters={{}}
      />,
    )
    expect(screen.getByRole('link', { name: 'ASML raises outlook' })).toHaveAttribute(
      'href',
      '/news?cluster=5',
    )
    expect(screen.getByText('Impact 72')).toBeInTheDocument()
    expect(screen.getByText('ASML Holding, World ETF')).toBeInTheDocument()
  })

  it('puts recommendations first, labelled as AI, and signals after', () => {
    renderAt(
      <SignalsWidget
        data={{
          items: [
            {
              kind: 'recommendation',
              id: 7,
              title: 'Direct new money to gold_hedge',
              severity: 'medium',
              time: '2026-10-14T17:30:00Z',
              departs: true,
            },
            {
              kind: 'signal',
              id: 1,
              title: 'gold_hedge is 20.0 pp under its target',
              severity: 'medium',
              time: '2026-10-14T08:00:00Z',
              departs: false,
            },
          ],
        }}
        config={{}}
        filters={{}}
      />,
    )
    const items = screen.getAllByRole('listitem')
    expect(within(items[0]).getByRole('link')).toHaveAttribute('href', '/insights?recommendation=7')
    expect(within(items[0]).getByText('AI-generated')).toBeInTheDocument()
    expect(within(items[0]).getByText('Departs from your principles')).toBeInTheDocument()
    expect(within(items[1]).getByRole('link')).toHaveAttribute('href', '/strategies')
    expect(within(items[1]).getByText('Signal')).toBeInTheDocument()
  })

  it('says when nothing is waiting', () => {
    renderAt(
      <SignalsWidget
        data={{ empty: true, reason: 'Nothing is waiting for you.' }}
        config={{}}
        filters={{}}
      />,
    )
    expect(screen.getByText('Nothing is waiting for you.')).toBeInTheDocument()
  })
})
