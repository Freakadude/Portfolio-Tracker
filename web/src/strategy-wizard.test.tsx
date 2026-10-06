import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Strategies } from './pages/Strategies'
import { GENERAL_US, mockApi, renderAt } from './test-utils'
import {
  blankAnswers,
  buildDefinition,
  currentMix,
  targetsAddUp,
  targetsFromMix,
} from './strategies/wizardLogic'

afterEach(() => vi.unstubAllGlobals())

const answers = () => ({
  ...blankAnswers(),
  groups: [
    { name: 'World', target: '70' },
    { name: 'Bonds', target: '30' },
  ],
  assignment: { IE0001: 'World', IE0002: 'Bonds' },
})

describe('the guided setup builds a strategy (FR-ST-01)', () => {
  it('writes sleeves with bands, trim thresholds and the chosen rules', () => {
    const d = buildDefinition(answers()) as {
      sleeves: Record<string, unknown>[]
      rules: { id: string }[]
      contribution_plan: unknown
    }
    expect(d.sleeves[0]).toMatchObject({
      id: 'World',
      members: ['IE0001'],
      target_pct: '70',
      soft_band_pp: '3',
      hard_band_pp: '6',
      trim_threshold_pct: '80',
    })
    expect(d.rules.map((r) => r.id)).toEqual(['drift', 'trims', 'drawdown', 'stale'])
    expect(d.contribution_plan).toBeNull()
  })

  it('caps a trim threshold at 100 and leaves it out when trimming is off', () => {
    const capped = buildDefinition({ ...answers(), groups: [{ name: 'World', target: '95' }] })
    expect((capped.sleeves as { trim_threshold_pct: string }[])[0].trim_threshold_pct).toBe('100')
    const off = buildDefinition({ ...answers(), trim: false })
    expect((off.sleeves as { trim_threshold_pct: unknown }[])[0].trim_threshold_pct).toBeNull()
    expect((off.rules as { id: string }[]).some((r) => r.id === 'trims')).toBe(false)
  })

  it('adds the concentration rule with its limit, and a plan with its reminder', () => {
    const d = buildDefinition({
      ...answers(),
      concentration: true,
      plan: { amount: '250', cadence: 'monthly', next: '' },
    }) as {
      rules: { id: string }[]
      risk_limits: Record<string, unknown>
      contribution_plan: object
    }
    expect(d.rules.map((r) => r.id)).toEqual(
      expect.arrayContaining(['concentration', 'contribution']),
    )
    expect(d.risk_limits.max_single_company_lookthrough_pct).toBe('10')
    expect(d.contribution_plan).toEqual({ amount_eur: '250', cadence: 'monthly', next_date: null })
  })

  it('sums each group from its holdings and makes whole-percent targets that add up to 100', () => {
    const holdings = [
      { key: 'A', name: 'A', weightPct: 33.4 },
      { key: 'B', name: 'B', weightPct: 33.3 },
      { key: 'C', name: 'C', weightPct: 33.3 },
    ]
    const mix = currentMix(holdings, { A: 'x', B: 'y', C: 'z' })
    expect(mix.x).toBeCloseTo(33.4)
    const targets = targetsFromMix(mix, ['x', 'y', 'z'])
    expect(targets).toEqual({ x: '34', y: '33', z: '33' })
    expect(targetsAddUp(Object.entries(targets).map(([name, target]) => ({ name, target })))).toBe(
      true,
    )
  })
})

describe('the guided setup page', () => {
  it('walks the steps, holds back until the targets add up, and saves the definition', async () => {
    const { calls } = mockApi({
      '/api/v1/settings/general': GENERAL_US,
      'GET /api/v1/strategies': [],
      '/api/v1/positions': {
        positions: [
          { instrument_id: 1, isin: 'IE0001', name: 'World ETF', weight: '0.7' },
          { instrument_id: 2, isin: 'IE0002', name: 'Bond ETF', weight: '0.3' },
        ],
        totals: {},
      },
      '/api/v1/instruments': [
        { id: 1, isin: 'IE0001', name: 'World ETF', sleeve_id: 10 },
        { id: 2, isin: 'IE0002', name: 'Bond ETF', sleeve_id: 11 },
      ],
      '/api/v1/sleeves': [
        { id: 10, name: 'World' },
        { id: 11, name: 'Bonds' },
      ],
      '/api/v1/strategies/check': { ok: true, problems: [], yaml: 'x', definition: {} },
      'POST /api/v1/strategies': {
        id: 5,
        name: 'My strategy',
        mode: 'off',
        current: {
          version: 1,
          created_at: '2026-10-06T10:00:00Z',
          note: null,
          yaml: '',
          definition: {},
        },
        versions: [],
      },
    })
    renderAt(<Strategies />, '/?guided=1')
    const next = async () =>
      userEvent.click(await screen.findByRole('button', { name: /^(Next|Skip)$/ }))
    expect(await screen.findByText('Step 1 of 8')).toBeInTheDocument()
    await next() // name
    // the groups are taken from your sleeves
    expect(await screen.findByLabelText('Group of World ETF')).toHaveValue('World')
    await next() // groups
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled() // targets are empty
    await userEvent.click(screen.getByRole('button', { name: "Use today's mix" }))
    expect(screen.getByLabelText('Target of World')).toHaveValue('70')
    expect(screen.getByRole('status')).toHaveTextContent('Total: 100 of 100 %')
    await next() // targets
    await next() // strictness
    await next() // alerts
    await next() // plan, skipped
    await next() // principles
    expect(await screen.findByText(/Alert when prices stop updating/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Save this strategy' }))
    const isSave = (c: { method: string; path: string }) =>
      c.method === 'POST' && c.path === '/api/v1/strategies'
    await waitFor(() => expect(calls.some(isSave)).toBe(true))
    const body = calls.find(isSave)?.body as {
      definition: { sleeves: { id: string; target_pct: string }[] }
      note: string
    }
    expect(body.note).toBe('guided setup')
    expect(body.definition.sleeves.map((s) => [s.id, s.target_pct])).toEqual([
      ['World', '70'],
      ['Bonds', '30'],
    ])
  })
})
