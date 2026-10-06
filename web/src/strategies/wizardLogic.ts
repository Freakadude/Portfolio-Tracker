import type { Definition } from './api'

/** The guided setup's answers and the strategy they turn into (FR-ST-01). Percentages and amounts
 * stay strings, as the server stores them as decimals; the numbers here are only for display and
 * for checking that the targets add up. */

export type Strictness = 'relaxed' | 'balanced' | 'tight'
export const STRICTNESS: Record<Strictness, { soft: string; hard: string }> = {
  relaxed: { soft: '5', hard: '10' },
  balanced: { soft: '3', hard: '6' },
  tight: { soft: '2', hard: '4' },
}

export const PRINCIPLES = [
  'Rebalance by directing new contributions to underweight sleeves before considering any sale.',
  'No emotionally driven profit-taking; trims happen only at pre-committed thresholds.',
]

export interface Holding {
  key: string // the ISIN
  name: string
  weightPct: number // share of the portfolio today, in percent
}

export interface Answers {
  name: string
  groups: { name: string; target: string }[]
  assignment: Record<string, string> // holding key -> group name
  strictness: Strictness
  drift: boolean
  trim: boolean
  trimOver: string // points above target
  drawdown: boolean
  drawdownPct: string
  stale: boolean
  concentration: boolean
  concentrationPct: string
  plan: { amount: string; cadence: 'weekly' | 'monthly' | 'quarterly'; next: string } | null
  principles: boolean[] // which of PRINCIPLES are kept
  ownPrinciples: string
}

export function blankAnswers(): Answers {
  return {
    name: 'My strategy',
    groups: [],
    assignment: {},
    strictness: 'balanced',
    drift: true,
    trim: true,
    trimOver: '10',
    drawdown: true,
    drawdownPct: '20',
    stale: true,
    concentration: false,
    concentrationPct: '10',
    plan: null,
    principles: PRINCIPLES.map(() => true),
    ownPrinciples: '',
  }
}

const hundredths = (text: string): number | null => {
  const n = Number(text.replace(',', '.').trim())
  return text.trim() !== '' && Number.isFinite(n) ? Math.round(n * 100) : null
}

/** The targets in hundredths of a percent, or null where one is empty or not a number. */
export function targetTotal(groups: Answers['groups']): number | null {
  let total = 0
  for (const g of groups) {
    const v = hundredths(g.target)
    if (v === null) return null
    total += v
  }
  return total
}
export const targetsAddUp = (groups: Answers['groups']) => targetTotal(groups) === 10000

/** What each group holds today, in percent of the portfolio. */
export function currentMix(holdings: Holding[], assignment: Record<string, string>) {
  const mix: Record<string, number> = {}
  for (const h of holdings) {
    const group = assignment[h.key]
    if (group) mix[group] = (mix[group] ?? 0) + h.weightPct
  }
  return mix
}

/** Today's mix as whole-percent targets that add up to exactly 100 (the rounding difference goes
 * to the largest group). */
export function targetsFromMix(
  mix: Record<string, number>,
  groups: string[],
): Record<string, string> {
  const total = groups.reduce((sum, g) => sum + (mix[g] ?? 0), 0)
  if (total <= 0) return {}
  const whole = Object.fromEntries(
    groups.map((g) => [g, Math.round(((mix[g] ?? 0) / total) * 100)]),
  )
  const gap = 100 - Object.values(whole).reduce((a, b) => a + b, 0)
  const largest = [...groups].sort((a, b) => (mix[b] ?? 0) - (mix[a] ?? 0))[0]
  whole[largest] += gap
  return Object.fromEntries(Object.entries(whole).map(([g, v]) => [g, String(v)]))
}

const plain = (n: number) => String(Math.round(n * 100) / 100)

/** The strategy definition the server's schema accepts. Holdings with no group are left out. */
export function buildDefinition(a: Answers): Definition {
  const { soft, hard } = STRICTNESS[a.strictness]
  const sleeves = a.groups.map((g) => {
    const target = hundredths(g.target)
    const over = hundredths(a.trimOver)
    const trim = a.trim && target !== null && over !== null ? Math.min(10000, target + over) : null
    return {
      id: g.name,
      members: Object.entries(a.assignment)
        .filter(([, group]) => group === g.name)
        .map(([key]) => key),
      target_pct: g.target.trim() || null,
      soft_band_pp: soft,
      hard_band_pp: hard,
      trim_threshold_pct: trim === null ? null : plain(trim / 100),
    }
  })
  const rule = (id: string, type: string, extra: Record<string, unknown>) => ({
    id,
    type,
    severity: 'medium',
    cooldown_days: 7,
    ...extra,
  })
  const rules: Record<string, unknown>[] = []
  if (a.drift) rules.push(rule('drift', 'drift_band', { applies_to: 'all' }))
  if (a.trim) {
    rules.push(
      rule('trims', 'trim_threshold', { applies_to: 'all', severity: 'high', cooldown_days: 14 }),
    )
  }
  if (a.drawdown) {
    rules.push(
      rule('drawdown', 'drawdown', {
        scope: 'position',
        threshold_pct: a.drawdownPct,
        cooldown_days: 14,
      }),
    )
  }
  if (a.stale) rules.push(rule('stale', 'stale_data', { severity: 'high', cooldown_days: 1 }))
  if (a.concentration) {
    rules.push(
      rule('concentration', 'concentration_limit', {
        dimension: 'company',
        limit_pct: a.concentrationPct,
      }),
    )
  }
  if (a.plan) {
    rules.push(rule('contribution', 'contribution_due', { severity: 'low', days_before: 3 }))
  }
  const principles = [
    ...PRINCIPLES.filter((_, i) => a.principles[i]),
    ...a.ownPrinciples
      .split('\n')
      .map((l) => l.trim())
      .filter(Boolean),
  ]
  return {
    name: a.name.trim() || 'My strategy',
    base_currency: 'EUR',
    principles,
    prefer_buys: true,
    macro_series: {},
    sleeves,
    risk_limits: {
      max_single_company_lookthrough_pct: a.concentration ? a.concentrationPct : null,
      max_thematic_total_pct: null,
    },
    rules,
    theses: [],
    contribution_plan: a.plan
      ? {
          amount_eur: a.plan.amount,
          cadence: a.plan.cadence,
          next_date: a.plan.next || null,
        }
      : null,
  }
}
