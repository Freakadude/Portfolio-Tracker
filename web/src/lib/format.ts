// Display formatting only. Money is computed on the server with exact decimals; values arrive as
// strings and are turned into numbers here purely for showing them.

export type NumberFormat = 'eu' | 'us'

export const localeFor = (format: NumberFormat) => (format === 'eu' ? 'nl-NL' : 'en-US')

const cache = new Map<string, Intl.NumberFormat>()
function formatter(key: string, locale: string, options: Intl.NumberFormatOptions) {
  const id = `${locale}|${key}`
  let f = cache.get(id)
  if (!f) {
    f = new Intl.NumberFormat(locale, options)
    cache.set(id, f)
  }
  return f
}

export function toNumber(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === '') return null
  const n = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(n) ? n : null
}

/** "€ 1.234,56" (eu) or "€1,234.56" (us). */
export function formatEur(
  value: string | number | null | undefined,
  format: NumberFormat,
  decimals = 2,
): string {
  const n = toNumber(value)
  if (n === null) return '–'
  return formatter(`eur${decimals}`, localeFor(format), {
    style: 'currency',
    currency: 'EUR',
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(n)
}

/** A plain number with a fixed number of decimals. */
export function formatNumber(
  value: string | number | null | undefined,
  format: NumberFormat,
  decimals = 2,
): string {
  const n = toNumber(value)
  if (n === null) return '–'
  return formatter(`num${decimals}`, localeFor(format), {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(n)
}

/** Units held: whole numbers stay whole, fractions show up to six places. */
export function formatQuantity(value: string | number | null | undefined, format: NumberFormat) {
  const n = toNumber(value)
  if (n === null) return '–'
  return formatter('qty', localeFor(format), { maximumFractionDigits: 6 }).format(n)
}

/** A ratio such as 0.0643 as "6.43%" (the API sends fractions). */
export function formatPercent(
  ratio: string | number | null | undefined,
  format: NumberFormat,
  decimals = 2,
): string {
  const n = toNumber(ratio)
  if (n === null) return '–'
  return formatter(`pct${decimals}`, localeFor(format), {
    style: 'percent',
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(n)
}

export type Direction = 'up' | 'down' | 'flat' | 'none'

/** Gains and losses are shown with a sign and an arrow as well as colour. */
export function direction(value: string | number | null | undefined, epsilon = 0.005): Direction {
  const n = toNumber(value)
  if (n === null) return 'none'
  if (Math.abs(n) < epsilon) return 'flat'
  return n > 0 ? 'up' : 'down'
}

export const ARROWS: Record<Direction, string> = { up: '▲', down: '▼', flat: '▬', none: '' }
export const SIGNS: Record<Direction, string> = { up: '+', down: '−', flat: '', none: '' }
