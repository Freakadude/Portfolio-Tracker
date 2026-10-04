import { describe, expect, it } from 'vitest'
import {
  direction,
  formatEur,
  formatNumber,
  formatPercent,
  formatQuantity,
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
  it('shows whole quantities whole and fractions to six places', () => {
    expect(formatQuantity('10', 'us')).toBe('10')
    expect(formatQuantity('0.123456789', 'us')).toBe('0.123457')
    expect(formatQuantity('1234.5', 'eu')).toBe('1.234,5')
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
