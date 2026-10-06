import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AskPanel } from './agent/Ask'
import { AskWidget } from './dashboards/widgets/Feeds'
import { GENERAL_US, mockApi, problem, renderAt } from './test-utils'

afterEach(() => vi.unstubAllGlobals())

const question = (over: Record<string, unknown> = {}) => ({
  id: 7,
  kind: 'ask',
  question: 'How far is gold from its target?',
  instrument_id: null,
  status: 'ok',
  answer: 'Gold is 20.0 pp under its target.',
  refused: false,
  reasons: [],
  citations: [{ tool: 'get_signals', note: 'the open drift signal' }],
  data: [
    {
      tool: 'get_signals',
      note: 'the open drift signal',
      input: { state: 'open' },
      result: 'gold_hedge is 20.0 pp under its target',
    },
  ],
  not_found: '',
  error: null,
  cost_eur: '0.0099',
  asked_at: '2026-10-06T10:00:00Z',
  finished_at: '2026-10-06T10:00:40Z',
  ai_label: 'AI-generated, not financial advice.',
  ...over,
})

const base = (extra: Record<string, unknown> = {}) => ({
  '/api/v1/settings/general': GENERAL_US,
  '/api/v1/agent/ask': [],
  ...extra,
})

describe('Ask the portfolio (FR-AG-08, FR-DB-09)', () => {
  it('puts the question, shows the answer with the data it used and its label', async () => {
    const { calls } = mockApi(
      base({
        'POST /api/v1/agent/ask': { run_id: 7, status: 'queued' },
        '/api/v1/agent/ask/7': question(),
      }),
    )
    renderAt(<AskPanel />)
    const send = screen.getByRole('button', { name: 'Ask' })
    expect(send).toBeDisabled() // nothing to ask yet
    await userEvent.type(screen.getByLabelText('Your question'), 'How far is gold from its target?')
    await userEvent.click(send)
    const answer = await screen.findByRole('article', { name: 'How far is gold from its target?' })
    expect(within(answer).getByText('Gold is 20.0 pp under its target.')).toBeInTheDocument()
    expect(within(answer).getByText('AI-generated, not financial advice.')).toBeInTheDocument()
    expect(within(answer).getByText('The data it used (1 tool)')).toBeInTheDocument()
    expect(within(answer).getByText('get_signals')).toBeInTheDocument()
    expect(within(answer).getByText('gold_hedge is 20.0 pp under its target')).toBeInTheDocument()
    const post = calls.find((c) => c.method === 'POST')
    expect(post?.body).toEqual({
      question: 'How far is gold from its target?',
      instrument_id: null,
    })
    expect(screen.getByLabelText('Your question')).toHaveValue('') // ready for the next one
  })

  it('says the agent is working while the worker has not answered', async () => {
    mockApi(
      base({
        'POST /api/v1/agent/ask': { run_id: 7, status: 'queued' },
        '/api/v1/agent/ask/7': question({ status: 'queued', answer: null, data: [] }),
      }),
    )
    renderAt(<AskPanel />)
    await userEvent.type(screen.getByLabelText('Your question'), 'What do I hold?')
    await userEvent.click(screen.getByRole('button', { name: 'Ask' }))
    expect(await screen.findByRole('status')).toHaveTextContent('The agent is looking at your data')
    expect(screen.getByRole('button', { name: 'Ask' })).toBeDisabled()
  })

  it('shows why an answer was not shown, and never its text', async () => {
    mockApi(
      base({
        'POST /api/v1/agent/ask': { run_id: 7, status: 'queued' },
        '/api/v1/agent/ask/7': question({
          answer: null,
          refused: true,
          reasons: ['a figure in the answer was not in the data this run read: 35.5 pp'],
          data: [],
        }),
      }),
    )
    renderAt(<AskPanel />)
    await userEvent.type(screen.getByLabelText('Your question'), 'How far is gold?')
    await userEvent.click(screen.getByRole('button', { name: 'Ask' }))
    expect(await screen.findByText(/did not pass the check/)).toBeInTheDocument()
    expect(screen.getByText(/35.5 pp/)).toBeInTheDocument()
    expect(screen.queryByText(/The data it used/)).not.toBeInTheDocument()
  })

  it('explains a refusal to ask, such as no API key', async () => {
    mockApi(
      base({
        'POST /api/v1/agent/ask': () =>
          problem(409, 'No API key', 'Add your Anthropic API key in Settings, Agent.'),
      }),
    )
    renderAt(<AskPanel />)
    await userEvent.type(screen.getByLabelText('Your question'), 'How far is gold?')
    await userEvent.click(screen.getByRole('button', { name: 'Ask' }))
    expect(await screen.findByText(/Add your Anthropic API key/)).toBeInTheDocument()
  })

  it('lists earlier questions below', async () => {
    mockApi(
      base({
        '/api/v1/agent/ask': [question({ id: 3, question: 'What changed this week?' })],
      }),
    )
    renderAt(<AskPanel />)
    const earlier = await screen.findByRole('region', { name: 'Earlier questions' })
    expect(within(earlier).getByText('What changed this week?')).toBeInTheDocument()
  })

  it('analyses a position without a typed question, or with one', async () => {
    const { calls } = mockApi(
      base({
        'POST /api/v1/agent/ask': { run_id: 7, status: 'queued' },
        '/api/v1/agent/ask/7': question({ kind: 'analyse_position', instrument_id: 5 }),
      }),
    )
    renderAt(<AskPanel instrumentId={5} />)
    await userEvent.click(screen.getByRole('button', { name: 'Analyse this position' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({
      question: null,
      instrument_id: 5,
    })
    await userEvent.type(
      screen.getByLabelText(/Your question \(or leave it empty/),
      'Why is it down?',
    )
    expect(screen.getByRole('button', { name: 'Ask' })).toBeEnabled()
    expect(calls.some((c) => c.path === '/api/v1/agent/ask' && c.method === 'GET')).toBe(true)
  })
})

describe('the ask widget', () => {
  const props = { config: {}, filters: { period: 'YTD', account: null } }

  it('says why it cannot be used when the agent is off, and otherwise shows the box', async () => {
    mockApi(base())
    const off = renderAt(
      <AskWidget
        {...props}
        data={{ empty: true, reason: 'The AI agent is switched off in Settings, Agent.' }}
      />,
    )
    expect(screen.getByText(/switched off/)).toBeInTheDocument()
    off.unmount()
    renderAt(<AskWidget {...props} data={{ empty: false, reason: null, show_last: 3 }} />)
    expect(await screen.findByLabelText('Your question')).toBeInTheDocument()
  })
})
