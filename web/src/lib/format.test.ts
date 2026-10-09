import { formatMoment } from './useFormat'
import { describe, expect, it } from 'vitest'
import {
  direction,
  formatEur,
  formatNumber,
  formatPercent,
  formatQuantity,
  formatSmallEur,
  roundNumbersIn,
  toNumber,
} from './format'

// Intl uses a non-breaking space between the symbol and the number in the Dutch format.
const plain = (s: string) => s.replace(/\s/g, ' ') // \s also matches the non-breaking space

describe('currency format is selectable', () => {
  it('formats the Dutch style as € 1.234,56', () => {
    expect(plain(formatEur('1234.56', 'eu'))).toBe('€ 1.234,56')
  })
  it('formats the English style as €1,234.56', () => {
    expect(formatEur('1234.56', 'us')).toBe('€1,234.56')
  })
  it('keeps decimals exactly as asked and shows a dash for no value', () => {
    expect(formatEur('2', 'us', 0)).toBe('€2')
    expect(formatEur(null, 'us')).toBe('–')
    expect(formatEur('', 'eu')).toBe('–')
    expect(formatEur('not a number', 'eu')).toBe('–')
  })
})

describe('numbers, quantities and percentages', () => {
  it('uses the chosen separators', () => {
    expect(formatNumber('1234.5', 'eu')).toBe('1.234,50')
    expect(formatNumber('1234.5', 'us')).toBe('1,234.50')
  })
  it('shows whole quantities whole and fractions to two places', () => {
    expect(formatQuantity('10', 'us')).toBe('10')
    expect(formatQuantity('0.123456789', 'us')).toBe('0.12')
    expect(formatQuantity('1234.5', 'eu')).toBe('1.234,5')
  })
  it('never shows more than two decimals, whatever a caller asks for', () => {
    expect(formatNumber('98.5432', 'us', 4)).toBe('98.54')
    expect(formatNumber('98.5432', 'us', 6)).toBe('98.54')
    expect(plain(formatEur('98.5432', 'us', 4))).toBe('€98.54')
    expect(plain(formatPercent('0.123456', 'us', 4))).toBe('12.35%')
    expect(formatNumber('98.5432', 'eu', 0)).toBe('99')
  })
  it('writes an amount below a cent as less than a cent, not as nothing', () => {
    expect(plain(formatSmallEur('0.0042', 'us'))).toBe('< €0.01')
    expect(plain(formatSmallEur('0.0213', 'us'))).toBe('€0.02')
    expect(plain(formatSmallEur('0', 'us'))).toBe('€0.00')
    expect(formatSmallEur(null, 'us')).toBe('–')
  })
  it('rounds the long numbers inside a text and leaves the rest alone', () => {
    const text =
      '{"weight": 0.123456, "price": "98.5432", "isin": "IE00B5BMR087", "n": 12, "d": "2026-10-09", "x": -1.2349, "v": 1.5}'
    expect(roundNumbersIn(text, 'us')).toBe(
      '{"weight": 0.12, "price": "98.54", "isin": "IE00B5BMR087", "n": 12, "d": "2026-10-09", "x": -1.23, "v": 1.5}',
    )
    expect(roundNumbersIn('rate 1.08523 and 1.085.234', 'eu')).toBe('rate 1,09 and 1.085.234')
  })
  it('turns the API fractions into percentages', () => {
    expect(plain(formatPercent('0.0643', 'us'))).toBe('6.43%')
    expect(plain(formatPercent('-0.5', 'us', 0))).toBe('-50%')
    expect(formatPercent(undefined, 'us')).toBe('–')
  })
  it('parses only real numbers', () => {
    expect(toNumber('12.5')).toBe(12.5)
    expect(toNumber('')).toBeNull()
    expect(toNumber('x')).toBeNull()
    expect(toNumber(undefined)).toBeNull()
  })
})

describe('gains and losses', () => {
  it('classifies the direction, treating sub-cent amounts as flat', () => {
    expect(direction('12.3')).toBe('up')
    expect(direction('-0.01')).toBe('down')
    expect(direction('0.001')).toBe('flat')
    expect(direction(null)).toBe('none')
  })
})

describe('formatMoment', () => {
  it('shows a moment in the owner time zone, and nothing for a missing or broken value', () => {
    expect(formatMoment('2026-10-06T13:20:00Z', 'Europe/Amsterdam')).toBe('6 Oct 2026, 15:20')
    expect(formatMoment('2026-10-06T13:20:00Z', 'America/New_York')).toBe('6 Oct 2026, 09:20')
    expect(formatMoment(null)).toBe('')
    expect(formatMoment('not a date')).toBe('')
  })
})
