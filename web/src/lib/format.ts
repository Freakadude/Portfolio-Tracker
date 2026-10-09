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

/** Nothing the owner reads shows more than two decimals, whatever the server calculated with.
 * The formatters below clamp to this, so no caller can ask for more. Fields you type into and
 * downloads are not "read" and keep the exact value. */
export const MAX_DECIMALS = 2
const clamp = (decimals: number) => Math.max(0, Math.min(decimals, MAX_DECIMALS))

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
  const places = clamp(decimals)
  return formatter(`eur${places}`, localeFor(format), {
    style: 'currency',
    currency: 'EUR',
    minimumFractionDigits: places,
    maximumFractionDigits: places,
  }).format(n)
}

/** An amount that is above zero but rounds to nothing (what one AI call costs) reads "< 0.01"
 * rather than "0.00", which would say it was free. */
export function formatSmallEur(
  value: string | number | null | undefined,
  format: NumberFormat,
): string {
  const n = toNumber(value)
  if (n !== null && n > 0 && n < 0.005) return `< ${formatEur(0.01, format)}`
  return formatEur(value, format)
}

/** A plain number with a fixed number of decimals. */
export function formatNumber(
  value: string | number | null | undefined,
  format: NumberFormat,
  decimals = 2,
): string {
  const n = toNumber(value)
  if (n === null) return '–'
  const places = clamp(decimals)
  return formatter(`num${places}`, localeFor(format), {
    minimumFractionDigits: places,
    maximumFractionDigits: places,
  }).format(n)
}

/** Units held: whole numbers stay whole, fractions show up to two places. */
export function formatQuantity(value: string | number | null | undefined, format: NumberFormat) {
  const n = toNumber(value)
  if (n === null) return '–'
  return formatter('qty', localeFor(format), { maximumFractionDigits: MAX_DECIMALS }).format(n)
}

/** The numbers with three or more decimals inside a text (data the agent read, as JSON or
 * prose), written with two, for showing. A number that rounds to a whole one keeps its two
 * places, so 0.001 reads 0.00 rather than 0. */
export function roundNumbersIn(text: string, format: NumberFormat): string {
  return text.replace(/(?<![\w.])-?\d+\.\d{3,}(?![\w.])/g, (found) =>
    formatNumber(found, format, MAX_DECIMALS),
  )
}

/** A ratio such as 0.0643 as "6.43%" (the API sends fractions). */
export function formatPercent(
  ratio: string | number | null | undefined,
  format: NumberFormat,
  decimals = 2,
): string {
  const n = toNumber(ratio)
  if (n === null) return '–'
  const places = clamp(decimals)
  return formatter(`pct${places}`, localeFor(format), {
    style: 'percent',
    minimumFractionDigits: places,
    maximumFractionDigits: places,
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
