// Chart colours are CSS variables (index.css) validated for colour-blind separation in light and
// dark. Identity colours are assigned in a fixed order, never cycled: past six things, the rest
// fold into "Other" and take the muted tone.
export const SERIES = [
  'var(--series-1)',
  'var(--series-2)',
  'var(--series-3)',
  'var(--series-4)',
  'var(--series-5)',
  'var(--series-6)',
] as const

export const OTHER = 'Other'
export const OTHER_COLOR = 'var(--muted)'

/** The colour of a named thing: its place in the sorted list of names, so it keeps its colour
 * when the values change. The seventh and later names are not given a hue. */
export function colorOf(keys: string[], key: string): string {
  if (key === OTHER) return OTHER_COLOR
  const index = [...keys]
    .filter((k) => k !== OTHER)
    .sort()
    .indexOf(key)
  return index >= 0 && index < SERIES.length ? SERIES[index] : OTHER_COLOR
}

/** Keep the largest `limit` entries and fold the rest into one "Other" entry. */
export function foldTail<T extends { key: string; value: number }>(
  items: T[],
  limit: number,
  make: (rest: T[], value: number) => T,
): T[] {
  if (items.length <= limit) return items
  const sorted = [...items].sort((a, b) => b.value - a.value)
  const head = sorted.slice(0, limit - 1)
  const rest = sorted.slice(limit - 1)
  return [
    ...head,
    make(
      rest,
      rest.reduce((sum, r) => sum + r.value, 0),
    ),
  ]
}

/** A diverging fill: blue for positive, red for negative, neutral grey at zero. `scale` is the
 * magnitude that gets the strongest tone; the tone never exceeds 60% so text stays readable. */
export function divergeFill(value: number | null, scale: number): string {
  if (value === null || !Number.isFinite(value)) return 'var(--diverge-mid)'
  const share = Math.min(Math.abs(value) / (scale || 1), 1) * 60
  const pole = value >= 0 ? 'var(--diverge-pos)' : 'var(--diverge-neg)'
  return `color-mix(in oklab, ${pole} ${share.toFixed(0)}%, var(--diverge-mid))`
}
