import { describe, expect, it } from 'vitest'
import { describeDefinition, extractYaml, problemsText } from './proposalText'

const DOC = 'strategy:\n  name: "Mine"\n  sleeves: []'

describe('reading the strategy out of what Claude answered', () => {
  it('takes the last fenced block that holds a strategy document', () => {
    const answer = [
      'Here is a first draft:',
      '```yaml',
      'strategy:\n  name: "Draft"',
      '```',
      'and the final one:',
      '```yaml',
      DOC,
      '```',
      'Other block:',
      '```',
      'not a strategy',
      '```',
    ].join('\n')
    expect(extractYaml(answer)).toBe(DOC)
  })

  it('takes a lone fenced block, or the whole text when nothing is fenced', () => {
    expect(extractYaml('```\nname: x\n```')).toBe('name: x')
    expect(extractYaml(`  ${DOC}\n`)).toBe(DOC)
  })

  it('writes the problems so they can be pasted back to Claude', () => {
    const text = problemsText([
      { line: 12, path: 'rules.0', message: 'unknown rule type' },
      { line: null, path: '', message: 'targets must add up' },
    ])
    expect(text).toContain('- line 12 (rules.0): unknown rule type')
    expect(text).toContain('- the document: targets must add up')
    expect(text).toContain('whole document again in one yaml code block')
  })
})

describe('describing a strategy in plain sentences', () => {
  const keys = (d: Record<string, unknown>) => describeDefinition(d).map((l) => l.key)

  it('lists the groups, their warnings, the rules and the regular investing', () => {
    const lines = describeDefinition({
      strategy: {
        name: 'Mine',
        principles: ['a', 'b'],
        sleeves: [
          {
            id: 'Core',
            members: ['IE1', 'IE2'],
            target_pct: '70',
            soft_band_pp: '3',
            hard_band_pp: '6',
          },
          { id: 'Themes', members: [], target_pct: null, trim_threshold_pct: '15' },
        ],
        risk_limits: { max_single_company_lookthrough_pct: '10' },
        rules: [
          { id: 'd', type: 'drift_band' },
          { id: 'dd', type: 'drawdown', scope: 'portfolio', threshold_pct: '25' },
          { id: 'off', type: 'stale_data', enabled: false },
        ],
        contribution_plan: { amount_eur: '500', cadence: 'monthly', next_date: '2026-11-01' },
      },
    })
    expect(lines.map((l) => l.key)).toEqual([
      'name',
      'sleeve',
      'bands',
      'sleeveNoTarget',
      'trim',
      'company',
      'rule.drift_band',
      'rule.drawdown_portfolio',
      'plan',
      'principles',
    ])
    expect(lines[1].params).toMatchObject({ name: 'Core', target: '70', n: 2 })
    expect(lines[2].params).toMatchObject({ soft: '3', hard: '6' })
    expect(lines[7].params).toMatchObject({ threshold: '25' })
  })

  it('copes with a bare definition and with nothing in it', () => {
    expect(keys({ name: 'Plain' })).toEqual(['name'])
    expect(keys({})).toEqual(['name'])
  })
})
