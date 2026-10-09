import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ChatDock } from './chat/ChatPanel'
import { GENERAL_US, mockApi, problem, renderAt } from './test-utils'

const THREAD = 'test-thread-1'

beforeEach(() => window.localStorage.setItem('folio.chat.thread', THREAD))
afterEach(() => {
  vi.unstubAllGlobals()
  window.localStorage.clear()
})

const turn = (over: Record<string, unknown> = {}) => ({
  id: 7,
  kind: 'ask',
  question: 'How is my portfolio doing?',
  instrument_id: null,
  thread: THREAD,
  status: 'ok',
  answer: 'It is up 4.2% this year.',
  refused: false,
  reasons: [],
  citations: [],
  data: [
    {
      tool: 'get_portfolio_summary',
      note: 'the totals',
      input: {},
      result: 'return 4.2%',
    },
  ],
  not_found: '',
  error: null,
  cost_eur: '0.01',
  asked_at: '2026-10-06T10:00:00Z',
  finished_at: '2026-10-06T10:00:40Z',
  ai_label: 'AI-generated, not financial advice.',
  ...over,
})

const USAGE = { enabled: true, key_set: true, paused: false, remaining_eur: '4.50' }
const chat = (turns: unknown[] | (() => unknown[])) =>
  typeof turns === 'function' ? turns : () => turns
const routes = (more: Record<string, unknown> = {}) => ({
  '/api/v1/settings/general': GENERAL_US,
  '/api/v1/agent/usage': USAGE,
  [`/api/v1/agent/chat/${THREAD}`]: chat([]),
  ...more,
})
const message = async () => {
  const box = await screen.findByLabelText('Your message')
  await vi.waitFor(() => expect(box).toBeEnabled())
  return box
}
const show = (path = '/news') => renderAt(<ChatDock />, path)

describe('the chat side panel (ADR 0049)', () => {
  it('is closed until the button is pressed, and the choice is remembered', async () => {
    mockApi(routes())
    const first = show()
    expect(screen.queryByRole('complementary')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Ask Folio' }))
    expect(await screen.findByRole('complementary', { name: 'Ask Folio' })).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Ask Folio' })).toBeNull() // the button steps aside
    first.unmount()

    show() // a reload: it opens where it was left
    expect(await screen.findByRole('complementary', { name: 'Ask Folio' })).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: 'Close the chat' }))
    expect(screen.queryByRole('complementary')).toBeNull()
    expect(screen.getByRole('button', { name: 'Ask Folio' })).toHaveFocus()
  })

  it('opens and closes with Ctrl+/ and closes with Escape from inside', async () => {
    mockApi(routes())
    show()
    const user = userEvent.setup()
    await user.keyboard('{Control>}/{/Control}')
    const panel = await screen.findByRole('complementary')
    await message() // focus moves into the message box once the agent is known to be ready
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('complementary')).toBeNull()
    await user.keyboard('{Control>}/{/Control}')
    expect(await screen.findByRole('complementary')).toBeVisible()
    await user.keyboard('{Control>}/{/Control}')
    expect(screen.queryByRole('complementary')).toBeNull()
    expect(panel).not.toBeInTheDocument()
  })

  it('sends a message with the page the owner is on and shows the reply with its data', async () => {
    let turns: unknown[] = []
    const { calls } = mockApi(
      routes({
        'POST /api/v1/agent/ask': () => {
          turns = [turn()]
          return { run_id: 7, status: 'queued' }
        },
        [`/api/v1/agent/chat/${THREAD}`]: () => turns,
      }),
    )
    window.localStorage.setItem('folio.chat.open', '1')
    show('/holdings/12')
    const user = userEvent.setup()
    expect(
      await screen.findByText(/Every number in an answer comes from your own data/),
    ).toBeVisible()
    await user.type(
      await screen.findByLabelText('Your message'),
      'How is my portfolio doing?{Enter}',
    )

    const log = await screen.findByRole('log', { name: 'Conversation' })
    expect(within(log).getByText('How is my portfolio doing?')).toBeVisible()
    expect(within(log).getByText('It is up 4.2% this year.')).toBeVisible()
    expect(within(log).getByText('AI-generated, not financial advice.')).toBeVisible()
    expect(within(log).getByText('The data it used (1 tool)')).toBeVisible()
    expect(calls.find((c) => c.method === 'POST' && c.path === '/api/v1/agent/ask')?.body).toEqual({
      question: 'How is my portfolio doing?',
      thread: THREAD,
      page: '/holdings/12',
    })
    expect(screen.getByLabelText('Your message')).toHaveValue('') // cleared once sent
  })

  it('offers first questions that are sent on a click', async () => {
    let turns: unknown[] = []
    const { calls } = mockApi(
      routes({
        'POST /api/v1/agent/ask': () => {
          turns = [turn({ question: "Is anything outside my strategy's bands?" })]
          return { run_id: 7, status: 'queued' }
        },
        [`/api/v1/agent/chat/${THREAD}`]: () => turns,
      }),
    )
    window.localStorage.setItem('folio.chat.open', '1')
    show()
    const first = await screen.findByRole('button', {
      name: "Is anything outside my strategy's bands?",
    })
    expect(screen.getByRole('link', { name: /Draft or revise a strategy/ })).toHaveAttribute(
      'href',
      '/strategies/assistant',
    )
    await vi.waitFor(() => expect(first).toBeEnabled())
    await userEvent.click(first)
    await vi.waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    expect(await screen.findByRole('log')).toHaveTextContent('It is up 4.2% this year.')
  })

  it('shows that it is working while the worker has not answered, and holds a second question', async () => {
    mockApi(
      routes({
        [`/api/v1/agent/chat/${THREAD}`]: () => [
          turn({ status: 'running', answer: null, data: [] }),
        ],
      }),
    )
    window.localStorage.setItem('folio.chat.open', '1')
    show()
    expect(await screen.findByRole('status')).toHaveTextContent('Looking at your data')
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'New chat' })).toBeDisabled()
  })

  it('ends each finished answer with what it cost, as a small amount', async () => {
    mockApi(
      routes({
        [`/api/v1/agent/chat/${THREAD}`]: () => [
          turn({ id: 7, cost_eur: '0.0213' }),
          turn({ id: 8, question: 'And a cheap one?', cost_eur: '0.0004' }),
          turn({ id: 9, question: 'A failed one?', status: 'failed', cost_eur: '0' }),
        ],
      }),
    )
    window.localStorage.setItem('folio.chat.open', '1')
    show()
    const costs = await screen.findAllByTestId('answer-cost')
    expect(costs.map((c) => c.textContent)).toEqual([
      expect.stringMatching(/^This answer cost .*0[.,]02\.$/),
      expect.stringMatching(/^This answer cost < .*0[.,]01\.$/),
    ]) // a turn that cost nothing says nothing about cost
  })

  it('shows no cost while the answer is still being written', async () => {
    mockApi(
      routes({
        [`/api/v1/agent/chat/${THREAD}`]: () => [
          turn({ status: 'running', answer: null, data: [], cost_eur: '0.005' }),
        ],
      }),
    )
    window.localStorage.setItem('folio.chat.open', '1')
    show()
    await screen.findByRole('status')
    expect(screen.queryByTestId('answer-cost')).toBeNull()
  })

  it('"New chat" starts a fresh conversation id', async () => {
    mockApi(routes({ [`/api/v1/agent/chat/${THREAD}`]: () => [turn()] }))
    window.localStorage.setItem('folio.chat.open', '1')
    show()
    await userEvent.click(await screen.findByRole('button', { name: 'New chat' }))
    expect(window.localStorage.getItem('folio.chat.thread')).not.toBe(THREAD)
    expect(
      await screen.findByText(/Every number in an answer comes from your own data/),
    ).toBeVisible()
  })

  it('cannot be used without the agent and a key, and says where to go', async () => {
    mockApi(routes({ '/api/v1/agent/usage': { ...USAGE, key_set: false } }))
    window.localStorage.setItem('folio.chat.open', '1')
    show()
    expect(await screen.findByRole('alert')).toHaveTextContent(/off or has no API key/)
    expect(screen.getByRole('link', { name: 'Open the agent settings' })).toHaveAttribute(
      'href',
      '/settings',
    )
    expect(screen.getByLabelText('Your message')).toBeDisabled()
  })

  it('shows what went wrong when a question cannot be put', async () => {
    mockApi(
      routes({
        'POST /api/v1/agent/ask': problem(409, 'Agent is off', 'The AI agent is switched off.'),
      }),
    )
    window.localStorage.setItem('folio.chat.open', '1')
    show()
    await userEvent.type(await message(), 'How is gold?{Enter}')
    expect(await screen.findByRole('alert')).toHaveTextContent('switched off')
    expect(screen.getByLabelText('Your message')).toHaveValue('How is gold?') // kept to retry
  })
})
