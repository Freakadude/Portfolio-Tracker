import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Interview } from './assistant/Interview'
import { GENERAL_US, mockApi, problem, renderAt } from './test-utils'

afterEach(() => vi.unstubAllGlobals())

const USAGE = { enabled: true, key_set: true, remaining_eur: '4.50', paused: false }
const session = (over: Record<string, unknown> = {}) => ({
  id: 3,
  mode: 'new',
  strategy_id: null,
  strategy_name: null,
  messages: [
    {
      role: 'assistant',
      text: 'Hello! What is the money for?',
      choices: ['Retirement', 'A house'],
    },
  ],
  draft: null,
  answers: 1,
  max_answers: 25,
  spent_eur: '0.0210',
  remaining_eur: '4.48',
  ...over,
})
const routes = (more: Record<string, unknown> = {}) => ({
  '/api/v1/settings/general': GENERAL_US,
  '/api/v1/agent/usage': USAGE,
  'GET /api/v1/strategies': [
    { id: 1, name: 'Old plan', mode: 'active', version: 1, updated_at: '2026-10-01T10:00:00Z' },
  ],
  ...more,
})
const show = () => renderAt(<Interview />, '/strategies/assistant', '/strategies/assistant')

describe('the strategy interview in the app (ADR 0048)', () => {
  it('cannot start without the agent and a key, and says where to go', async () => {
    mockApi(routes({ '/api/v1/agent/usage': { ...USAGE, key_set: false } }))
    show()
    expect(await screen.findByRole('alert')).toHaveTextContent(/off or has no API key/)
    expect(screen.getByRole('button', { name: 'Start the interview' })).toBeDisabled()
  })

  it('starts, shows the question with suggested answers, and sends a picked answer', async () => {
    const { calls } = mockApi(
      routes({
        'POST /api/v1/assistant/sessions': session(),
        'GET /api/v1/assistant/sessions/3': session(),
        'POST /api/v1/assistant/sessions/3/messages': session({
          messages: [
            { role: 'assistant', text: 'Hello! What is the money for?', choices: [] },
            { role: 'user', text: 'Retirement', choices: [] },
            { role: 'assistant', text: 'And for how many years?', choices: [] },
          ],
          answers: 2,
        }),
      }),
    )
    show()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Start the interview' }))
    const log = await screen.findByRole('log')
    expect(log).toHaveTextContent('Hello! What is the money for?')
    expect(screen.getByText(/has cost .*0[.,]02.* so far \(answer 1 of 25\)/)).toBeVisible()
    expect(calls.find((c) => c.path === '/api/v1/assistant/sessions')?.body).toEqual({
      mode: 'new',
      strategy_id: null,
    })

    await user.click(screen.getByRole('button', { name: 'Retirement' }))
    expect(await screen.findByText('And for how many years?')).toBeVisible()
    expect(calls.find((c) => c.path.endsWith('/messages'))?.body).toEqual({ text: 'Retirement' })
    expect(screen.queryByRole('button', { name: 'A house' })).toBeNull() // old suggestions go
  })

  it('shows the drafted strategy as sentences with the way to save it', async () => {
    mockApi(
      routes({
        'POST /api/v1/assistant/sessions': session({
          draft: {
            yaml: 'strategy:\n  name: "Mine"\n',
            definition: {
              name: 'Mine',
              sleeves: [{ id: 'Core', members: [], target_pct: '80' }],
              rules: [{ id: 'd', type: 'drift_band' }],
            },
          },
        }),
      }),
    )
    show()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Start the interview' }))
    expect(await screen.findByText(/The helper has drafted a strategy/)).toBeVisible()
    expect(screen.getByText(/Core: no target yet|Core: target 80% of the portfolio/)).toBeVisible()
    expect(screen.getByText('Warn when a group drifts outside its band.')).toBeVisible()
    expect(
      screen.getByRole('button', { name: 'Save as a new strategy (switched off)' }),
    ).toBeVisible()
  })

  it('revises a chosen strategy and shows what happened when the budget is used up', async () => {
    const { calls } = mockApi(
      routes({
        'POST /api/v1/assistant/sessions': session({
          mode: 'revise',
          strategy_id: 1,
          strategy_name: 'Old plan',
        }),
        'POST /api/v1/assistant/sessions/3/messages': problem(
          409,
          'Budget',
          'The AI budget for 2026-10 is used up.',
        ),
      }),
    )
    show()
    const user = userEvent.setup()
    await user.click(await screen.findByLabelText('Revise a strategy I have'))
    await user.selectOptions(screen.getByLabelText('Strategy to revise'), '1')
    await user.click(screen.getByRole('button', { name: 'Start the interview' }))
    expect(await screen.findByRole('heading', { name: 'Revising Old plan' })).toBeVisible()
    expect(calls.find((c) => c.path === '/api/v1/assistant/sessions')?.body).toEqual({
      mode: 'revise',
      strategy_id: 1,
    })
    await user.type(screen.getByLabelText('Your answer'), 'Lower the drawdown level.')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('budget for 2026-10 is used up')
  })
})
