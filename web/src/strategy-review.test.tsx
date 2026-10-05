import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { StrategyReview } from './strategies/Review'
import { GENERAL_US, mockApi, problem, renderAt } from './test-utils'

afterEach(() => vi.unstubAllGlobals())

const REVIEW = (over: Record<string, unknown> = {}) => ({
  quarter: '2026Q3',
  start: '2026-07-01',
  end: '2026-09-30',
  complete: true,
  strategy: 'My strategy',
  sleeves: [
    {
      id: 'gold',
      target_pct: '40',
      month_ends: [
        { day: '2026-07-31', weight: '0.4', drift_pp: '0.00' },
        { day: '2026-08-31', weight: '0.31', drift_pp: '-9.00' },
        { day: '2026-09-30', weight: '0.38', drift_pp: '-2.00' },
      ],
      worst: { day: '2026-08-31', weight: '0.31', drift_pp: '-9.00' },
      days_outside_hard: 12,
      days_outside_soft: 0,
    },
    {
      id: 'thematic',
      target_pct: null,
      month_ends: [],
      worst: null,
      days_outside_hard: 0,
      days_outside_soft: 0,
    },
  ],
  signals: [{ rule_id: 'drift', count: 3, worst_severity: 'high' }],
  recommendations: { made: 2, by_status: { accepted: 1, rejected: 1 }, by_action: {} },
  days_with_data: 92,
  notes: ['thematic has no target yet, so its drift cannot be judged.'],
  text: 'x',
  ...over,
})

const PATH = '/strategies/review?quarter=2026Q3'
const show = () => renderAt(<StrategyReview />, PATH, '/strategies/review')

describe('the quarterly review page (FR-ST-08)', () => {
  it('shows drift by sleeve, the signals and what became of the advice', async () => {
    mockApi({ '/api/v1/settings/general': GENERAL_US, '/api/v1/strategy-review': REVIEW() })
    show()
    const table = await screen.findByRole('table', {
      name: 'Drift of each sleeve from its target',
    })
    const gold = within(table).getByRole('row', { name: /gold/ })
    expect(gold).toHaveTextContent('40%')
    expect(gold).toHaveTextContent('07: 0.0 pp · 08: -9.0 pp · 09: -2.0 pp')
    expect(gold).toHaveTextContent('-9.0 pp (2026-08-31)')
    expect(gold).toHaveTextContent('12 hard, 0 soft')
    expect(within(table).getByRole('row', { name: /thematic/ })).toHaveTextContent('no target')
    expect(screen.getByText(/3 time\(s\), worst high/)).toBeInTheDocument()
    expect(screen.getByText('2 made: 1 accepted, 1 rejected')).toBeInTheDocument()
    expect(screen.getByText(/cannot be judged/)).toBeInTheDocument()
  })

  it('puts a finished quarter in the inbox, once', async () => {
    let posted = 0
    const { calls } = mockApi({
      '/api/v1/settings/general': GENERAL_US,
      '/api/v1/strategy-review': REVIEW(),
      'POST /api/v1/strategy-review/post': () => ({ quarter: '2026Q3', posted: ++posted === 1 }),
    })
    show()
    await userEvent.click(await screen.findByRole('button', { name: 'Put in the inbox' }))
    expect(await screen.findByText('Put in the inbox.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Put in the inbox' }))
    expect(await screen.findByText(/already has its item/)).toBeInTheDocument()
    expect(calls.filter((c) => c.method === 'POST')).toHaveLength(2)
  })

  it('is a preview, without the button, while the quarter is not over', async () => {
    mockApi({
      '/api/v1/settings/general': GENERAL_US,
      '/api/v1/strategy-review': REVIEW({ complete: false }),
    })
    show()
    expect(await screen.findByText(/not over yet/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Put in the inbox' })).not.toBeInTheDocument()
  })

  it('asks another quarter and says when no strategy is active', async () => {
    const { calls } = mockApi({
      '/api/v1/settings/general': GENERAL_US,
      '/api/v1/strategy-review': () => problem(404, 'No active strategy', 'Make one active.'),
    })
    show()
    expect(await screen.findByText(/Make a strategy active to get a review/)).toBeInTheDocument()
    await userEvent.selectOptions(screen.getByLabelText('Quarter'), '2026Q2')
    await waitFor(() =>
      expect(calls.filter((c) => c.path === '/api/v1/strategy-review').length).toBeGreaterThan(1),
    )
  })
})
