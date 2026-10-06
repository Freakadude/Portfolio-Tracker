import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Backtest } from './strategies/Backtest'
import { GENERAL_US, mockApi, problem, renderAt } from './test-utils'

afterEach(() => vi.unstubAllGlobals())

const RESULT = {
  strategy: 'My strategy',
  version: 3,
  start: '2025-10-06',
  end: '2026-10-06',
  days_checked: 250,
  firings: [
    {
      date: '2026-01-10',
      rule_id: 'drift',
      rule_type: 'drift_band',
      subject: 'gold',
      severity: 'high',
      value: '10.0',
      message: 'gold is 10.0 pp under its target (hard band 8 pp)',
    },
    {
      date: '2026-01-17',
      rule_id: 'drift',
      rule_type: 'drift_band',
      subject: 'gold',
      severity: 'high',
      value: '10.0',
      message: 'gold is 10.0 pp under its target (hard band 8 pp)',
    },
  ],
  rules: [
    {
      rule_id: 'drift',
      rule_type: 'drift_band',
      backtestable: true,
      reason: null,
      days_true: 22,
      fired: 2,
    },
    {
      rule_id: 'stale',
      rule_type: 'stale_data',
      backtestable: false,
      reason: "It looks at how fresh today's prices are.",
      days_true: 0,
      fired: 0,
    },
  ],
  notes: [],
  note: 'Nothing is saved or sent.',
}

const show = () => renderAt(<Backtest id={4} ruleIds={['drift', 'stale']} />)

describe('the backtest (FR-ST-06)', () => {
  it('lists the dates a rule would have fired with the values, and what could not be tested', async () => {
    const { calls } = mockApi({
      '/api/v1/settings/general': GENERAL_US,
      'POST /api/v1/strategies/4/backtest': RESULT,
    })
    show()
    await userEvent.click(screen.getByRole('button', { name: 'Run the backtest' }))
    expect(await screen.findByRole('status')).toHaveTextContent(
      '250 trading days checked against version 3; the rules would have fired 2 time(s).',
    )
    const firings = screen.getByRole('table', { name: 'The days the rules would have fired' })
    const rows = within(firings).getAllByRole('row').slice(1)
    expect(rows).toHaveLength(2)
    expect(rows[0]).toHaveTextContent('2026-01-10')
    expect(rows[0]).toHaveTextContent('gold is 10.0 pp under its target')
    expect(rows[0]).toHaveTextContent('10.0') // the drift in percentage points
    expect(rows[1]).toHaveTextContent('2026-01-17')
    const rules = screen.getByRole('table', { name: 'What each rule did in the range' })
    expect(within(rules).getByRole('row', { name: /drift/ })).toHaveTextContent('22')
    expect(within(rules).getByRole('row', { name: /stale/ })).toHaveTextContent(
      "Not backtestable: It looks at how fresh today's prices are.",
    )
    const body = calls.find((c) => c.method === 'POST')?.body as Record<string, unknown>
    expect(body.rule_ids).toBeNull()
    expect(String(body.start)).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    expect(screen.getByText('Nothing is saved or sent.')).toBeInTheDocument()
  })

  it('tests one rule over a range of your choosing', async () => {
    const { calls } = mockApi({
      '/api/v1/settings/general': GENERAL_US,
      'POST /api/v1/strategies/4/backtest': { ...RESULT, firings: [], days_checked: 12 },
    })
    show()
    await userEvent.selectOptions(screen.getByLabelText('Rule'), 'drift')
    await userEvent.clear(screen.getByLabelText('From'))
    await userEvent.type(screen.getByLabelText('From'), '2026-02-01')
    await userEvent.clear(screen.getByLabelText('To'))
    await userEvent.type(screen.getByLabelText('To'), '2026-02-15')
    await userEvent.click(screen.getByRole('button', { name: 'Run the backtest' }))
    expect(await screen.findByText('Nothing would have fired in this range.')).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({
      rule_ids: ['drift'],
      start: '2026-02-01',
      end: '2026-02-15',
    })
  })

  it('explains a request that cannot be run', async () => {
    mockApi({
      '/api/v1/settings/general': GENERAL_US,
      'POST /api/v1/strategies/4/backtest': () =>
        problem(422, 'Cannot run the backtest', 'Choose a range of at most 1100 days.'),
    })
    show()
    await userEvent.click(screen.getByRole('button', { name: 'Run the backtest' }))
    await waitFor(() =>
      expect(screen.getByText(/Choose a range of at most 1100 days/)).toBeInTheDocument(),
    )
  })
})
