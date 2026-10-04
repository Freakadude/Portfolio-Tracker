import { describe, expect, it } from 'vitest'
import { resources } from './i18n'

const sources = import.meta.glob('./**/*.tsx', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

function has(path: string): boolean {
  let node: unknown = resources
  for (const part of path.split('.')) {
    if (typeof node !== 'object' || node === null || !(part in node)) return false
    node = (node as Record<string, unknown>)[part]
  }
  return typeof node === 'string'
}

/** Plural keys are stored as key_one and key_other. */
const exists = (key: string) => has(key) || has(`${key}_one`) || has(`${key}_other`)

describe('translations', () => {
  it('has every key the code asks for', () => {
    const missing: string[] = []
    for (const [file, text] of Object.entries(sources)) {
      if (file.includes('.test.')) continue
      for (const match of text.matchAll(/\bt\(\s*(['`])((?:(?!\1).)+?)\1/g)) {
        const key = match[2]
        if (key.includes('${')) continue // built at run time, such as assetClass.${code}
        if (!exists(key)) missing.push(`${file}: ${key}`)
      }
    }
    expect(missing).toEqual([])
  })

  it('has every dynamic key family the code builds', () => {
    const families: Record<string, string[]> = {
      assetClass: ['ETF', 'ETC', 'EQUITY', 'BOND', 'FUND', 'CASH', 'OTHER'],
      'transactions.types': [
        'buy',
        'sell',
        'dividend',
        'interest',
        'fee',
        'tax',
        'split',
        'transfer_in',
        'transfer_out',
        'deposit',
        'withdrawal',
      ],
      delta: ['up', 'down', 'flat', 'none'],
      'holdings.tabs': ['positions', 'instruments'],
      'instruments.filters': ['active', 'archived', 'all'],
      'position.chartRanges': ['1M', '3M', '1Y', 'MAX'],
    }
    const missing = Object.entries(families).flatMap(([family, keys]) =>
      keys.filter((k) => !has(`${family}.${k}`)).map((k) => `${family}.${k}`),
    )
    expect(missing).toEqual([])
  })

  it('keeps strings out of the components: no hard-coded sentences in headings and buttons', () => {
    const offenders: string[] = []
    for (const [file, text] of Object.entries(sources)) {
      if (file.includes('.test.') || file.includes('main.tsx')) continue
      for (const match of text.matchAll(
        /<(h1|h2|h3|button|Button|th|label)\b[^>]*>\s*([A-Z][a-z]+(?: [a-z]+)+)\s*</g,
      )) {
        offenders.push(`${file}: "${match[2]}"`)
      }
    }
    expect(offenders).toEqual([])
  })
})
