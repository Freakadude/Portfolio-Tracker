// Exact decimal helpers for the few places the browser must turn one entered number into
// another (an exchange rate and its reciprocal). They work on strings with BigInt, so there is
// no floating-point rounding anywhere on the way.

const DECIMAL = /^\s*(-?)(\d*)(?:[.,](\d+))?\s*$/

/** Parse "1.0950" or "1,0950" into an integer and the number of decimals it carries. */
export function parseDecimal(text: string): { value: bigint; scale: number } | null {
  const m = DECIMAL.exec(text)
  if (!m || (m[2] === '' && (m[3] ?? '') === '')) return null
  const fraction = m[3] ?? ''
  const value = BigInt(`${m[2] || '0'}${fraction}`) * (m[1] === '-' ? -1n : 1n)
  return { value, scale: fraction.length }
}

export function isPositiveDecimal(text: string): boolean {
  const parsed = parseDecimal(text)
  return parsed !== null && parsed.value > 0n
}

/** 1 / rate, rounded half-to-even to `places` decimals, as a plain decimal string. */
export function reciprocal(rate: string, places = 10): string | null {
  const parsed = parseDecimal(rate)
  if (!parsed || parsed.value <= 0n) return null
  // 1 / (value / 10^scale) = 10^scale / value; scale it by 10^places to get an integer
  const numerator = 10n ** BigInt(parsed.scale + places)
  const quotient = numerator / parsed.value
  const remainder = numerator % parsed.value
  const twice = remainder * 2n
  let result = quotient
  if (twice > parsed.value || (twice === parsed.value && quotient % 2n === 1n)) result += 1n
  const digits = result.toString().padStart(places + 1, '0')
  const whole = digits.slice(0, digits.length - places)
  const fraction = digits.slice(digits.length - places)
  return places === 0 ? whole : `${whole}.${fraction}`
}

/** Drop pointless trailing zeros: "1.2000" becomes "1.2". */
export function trimDecimal(text: string): string {
  return text.includes('.') ? text.replace(/0+$/, '').replace(/\.$/, '') : text
}

/** How many whole units `amount` buys at `price` when `weightPct` percent of it is spent on
 * them: floor(amount x weight / 100 / price), computed exactly. Null when an input is not a
 * positive number. Whole units only (owner decision Q8); the leftover stays in cash. */
export function wholeUnits(amount: string, weightPct: string, price: string): number | null {
  const a = parseDecimal(amount)
  const w = parseDecimal(weightPct)
  const p = parseDecimal(price)
  if (!a || !w || !p || a.value <= 0n || w.value < 0n || p.value <= 0n) return null
  // (A/10^sa) x (W/10^sw) / 100 / (P/10^sp) = A x W x 10^sp / (100 x P x 10^(sa+sw))
  const numerator = a.value * w.value * 10n ** BigInt(p.scale)
  const denominator = 100n * p.value * 10n ** BigInt(a.scale + w.scale)
  return Number(numerator / denominator)
}
