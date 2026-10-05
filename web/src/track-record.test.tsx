import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { TrackRecord } from './agent/TrackRecord'
import { GENERAL_US, mockApi, renderAt } from './test-utils'

afterEach(() => vi.unstubAllGlobals())

const horizon = (days: number, over: Record<string, unknown> = {}) => ({
  days,
  measured: 0,
  scored: 0,
  hits: 0,
  hit_rate: null,
  avg_return: null,
  ...over,
})

const RECORD = (decisionHorizon = 30) => ({
  total: 4,
  decision_horizon: decisionHorizon,
  note: 'Price only, in each instrument trading currency. Read small samples with care.',
  actions: [
    {
      action_type: 'direct_contribution',
      scored_type: true,
      count: 3,
      by_horizon: [
        horizon(7),
        horizon(30, { measured: 2, scored: 2, hits: 1, hit_rate: '0.500000', avg_return: '0.015' }),
        horizon(90),
      ],
    },
    {
      action_type: 'watch',
      scored_type: false,
      count: 1,
      by_horizon: [horizon(7), horizon(30, { measured: 1, avg_return: '0.10' }), horizon(90)],
    },
  ],
  decisions: [
    {
      decision: 'accepted',
      count: 1,
      stats: horizon(decisionHorizon, { measured: 1, scored: 1, hits: 1, hit_rate: '1' }),
    },
    { decision: 'rejected', count: 1, stats: horizon(decisionHorizon) },
    { decision: 'undecided', count: 2, stats: horizon(decisionHorizon) },
  ],
})

describe('the track record (FR-AG-06)', () => {
  it('shows hit rate and price change by action type, and says what is not scored', async () => {
    mockApi({
      '/api/v1/settings/general': GENERAL_US,
      '/api/v1/agent/track-record': RECORD(),
    })
    renderAt(<TrackRecord />)
    const table = await screen.findByRole('table', {
      name: "Hit rate and price change of the agent's recommendations by action type",
    })
    const buy = within(table).getByRole('row', { name: /Direct new money/ })
    expect(buy).toHaveTextContent('50%')
    expect(buy).toHaveTextContent('1 of 2')
    expect(buy).toHaveTextContent('1.50%')
    const watch = within(table).getByRole('row', { name: /Watch/ })
    expect(watch).toHaveTextContent('not scored')
    expect(watch).toHaveTextContent('10.00%') // measured, never a hit or a miss
    expect(screen.getByText(/Price only/)).toBeInTheDocument()
    const decisions = screen.getByRole('table', { name: 'Hit rate by your decision' })
    expect(within(decisions).getByRole('row', { name: /Accepted/ })).toHaveTextContent('100%')
  })

  it('asks for another horizon', async () => {
    const { calls } = mockApi({
      '/api/v1/settings/general': GENERAL_US,
      '/api/v1/agent/track-record': (request: Request) =>
        RECORD(Number(new URL(request.url).searchParams.get('horizon'))),
    })
    renderAt(<TrackRecord />)
    await screen.findByRole('table', { name: /Hit rate and price change/ })
    await userEvent.selectOptions(screen.getByLabelText('Horizon'), '90')
    await waitFor(() =>
      expect(calls.some((c) => c.path === '/api/v1/agent/track-record' && c.body === null)).toBe(
        true,
      ),
    )
    expect(await screen.findByText('By what you decided, after 90 days')).toBeInTheDocument()
  })

  it('says so when there is nothing to measure yet', async () => {
    mockApi({
      '/api/v1/settings/general': GENERAL_US,
      '/api/v1/agent/track-record': { ...RECORD(), total: 0, actions: [], decisions: [] },
    })
    renderAt(<TrackRecord />)
    expect(await screen.findByText(/Nothing to measure yet/)).toBeInTheDocument()
  })
})
