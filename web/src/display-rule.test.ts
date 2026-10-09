import { describe, expect, it } from 'vitest'

// Nothing the owner reads shows more than two decimals (ADR 0052). The formatters clamp, so the
// ways to break the rule are the ones that go around them; this finds them in the source.

const raw = import.meta.glob(['./**/*.ts', './**/*.tsx', '!./**/*.test.*', '!./**/*.d.ts'], {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

const files = Object.entries(raw).map(([name, text]) => ({ name, text }))

const find = (pattern: RegExp) =>
  files.flatMap((f) => [...f.text.matchAll(pattern)].map((m) => `${f.name}: ${m[0]}`))

describe('the two-decimal display rule', () => {
  it('looks at the whole source', () => {
    expect(files.length).toBeGreaterThan(100)
  })

  it('asks no formatter for more than two decimals', () => {
    expect(
      find(
        /\b(?:eur|num|pct|formatEur|formatNumber|formatPercent)\([^()]*,\s*(?:[3-9]|\d{2,})\s*\)/g,
      ),
    ).toEqual([])
  })

  it('does not round to more than two decimals on its own', () => {
    expect(find(/\.toFixed\(\s*(?:[3-9]|\d{2,})\s*\)/g)).toEqual([])
    expect(find(/\.toPrecision\(/g)).toEqual([])
    expect(find(/(?:maximum|minimum)FractionDigits:\s*(?:[3-9]|\d{2,})/g)).toEqual([])
  })

  it('does not print a price, quantity or percentage straight from the server', () => {
    // {tx.price} in a cell; value={...} in a field you type into is fine and not matched
    expect(
      find(
        /(?<![=\w])\{[\w.?]*\.(?:price|delayed_price|quantity|quantity_before|quantity_after|target_pct|band_pct|soft_band_pp|hard_band_pp|weight_pct|amount_eur|cost_eur|threshold|last_value|trust_weight|budget_eur|news_share_eur|market_value_native|cost_basis_native|unrealized_pnl_native|ratio)\}/g,
      ),
    ).toEqual([])
  })
})
