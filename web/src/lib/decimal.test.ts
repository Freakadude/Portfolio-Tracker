import { describe, expect, it } from 'vitest'
import { isPositiveDecimal, parseDecimal, reciprocal, trimDecimal } from './decimal'

describe('parsing', () => {
  it('reads dot and comma decimals exactly', () => {
    expect(parseDecimal('1.0950')).toEqual({ value: 10950n, scale: 4 })
    expect(parseDecimal('1,5')).toEqual({ value: 15n, scale: 1 })
    expect(parseDecimal(' 12 ')).toEqual({ value: 12n, scale: 0 })
    expect(parseDecimal('-0.5')).toEqual({ value: -5n, scale: 1 })
    expect(parseDecimal('.5')).toEqual({ value: 5n, scale: 1 })
  })
  it('refuses what is not a number', () => {
    for (const bad of ['', 'abc', '1.2.3', '1e5', '-', '.']) expect(parseDecimal(bad)).toBeNull()
  })
  it('knows a positive number when it sees one', () => {
    expect(isPositiveDecimal('0.0001')).toBe(true)
    expect(isPositiveDecimal('0')).toBe(false)
    expect(isPositiveDecimal('-1')).toBe(false)
    expect(isPositiveDecimal('x')).toBe(false)
  })
})

describe('the reciprocal of an exchange rate', () => {
  it('matches the server: 1 / 1.0950 to ten decimals', () => {
    expect(reciprocal('1.0950')).toBe('0.9132420091')
  })
  it('matches the value the API tests expect for 0.82805', () => {
    expect(reciprocal('0.82805')).toBe('1.2076565425')
  })
  it('is exact where the answer is exact', () => {
    expect(reciprocal('2')).toBe('0.5000000000')
    expect(reciprocal('0.8')).toBe('1.2500000000')
    expect(reciprocal('1')).toBe('1.0000000000')
    expect(reciprocal('4', 2)).toBe('0.25')
  })
  it('rounds half to even, like the server', () => {
    expect(reciprocal('8', 2)).toBe('0.12') // 0.125 -> 0.12
    expect(reciprocal('16', 3)).toBe('0.062') // 0.0625 -> 0.062
    expect(reciprocal('1.6', 3)).toBe('0.625')
    expect(reciprocal('6', 1)).toBe('0.2') // 0.1666... -> 0.2
  })
  it('takes comma decimals and rejects zero, negatives and junk', () => {
    expect(reciprocal('1,25', 4)).toBe('0.8000')
    expect(reciprocal('0')).toBeNull()
    expect(reciprocal('-2')).toBeNull()
    expect(reciprocal('abc')).toBeNull()
  })
  it('handles very large and very small rates without losing digits', () => {
    expect(reciprocal('0.0001', 2)).toBe('10000.00')
    expect(reciprocal('123456789.123456789', 12)).toBe('0.000000008100')
  })
})

describe('trimming', () => {
  it('drops trailing zeros only after a decimal point', () => {
    expect(trimDecimal('1.2000')).toBe('1.2')
    expect(trimDecimal('1.0000')).toBe('1')
    expect(trimDecimal('100')).toBe('100')
    expect(trimDecimal('0.9132420091')).toBe('0.9132420091')
  })
})
