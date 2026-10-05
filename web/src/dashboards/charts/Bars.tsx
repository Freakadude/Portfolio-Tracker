import { useState } from 'react'
import { Legend } from './ChartFrame'

export interface DivergingRow {
  key: string
  value: number // signed
  band?: number | null // the shaded range around zero that counts as on target
  text: string // the label at the tip of the bar
  onSelect?: () => void
}

/** Horizontal bars either side of a zero line: positive in the blue pole, negative in the red,
 * the on-target band shaded behind them. Bars are thin, rounded only at their data end. */
export function DivergingBars({
  rows,
  label,
  positive,
  negative,
}: {
  rows: DivergingRow[]
  label: string
  positive: string
  negative: string
}) {
  const reach = Math.max(1e-9, ...rows.map((r) => Math.max(Math.abs(r.value), r.band ?? 0)))
  return (
    <div className="space-y-1" role="group" aria-label={label}>
      {rows.map((row) => {
        const width = (Math.abs(row.value) / reach) * 50
        const band = row.band ? (row.band / reach) * 50 : 0
        const interactive = Boolean(row.onSelect)
        return (
          <div key={row.key} className="flex items-center gap-2 text-sm">
            <span className="w-28 shrink-0 truncate" title={row.key}>
              {row.key}
            </span>
            <button
              type="button"
              disabled={!interactive}
              onClick={row.onSelect}
              aria-label={`${row.key}: ${row.text}`}
              title={`${row.key}: ${row.text}`}
              className="relative h-6 flex-1 disabled:cursor-default"
            >
              {band > 0 && (
                <span
                  aria-hidden="true"
                  className="absolute inset-y-0 rounded-sm bg-border/50"
                  style={{ left: `${50 - band}%`, width: `${band * 2}%` }}
                />
              )}
              <span aria-hidden="true" className="absolute inset-y-0 left-1/2 w-px bg-muted/60" />
              <span
                aria-hidden="true"
                className={`absolute top-1 h-4 ${row.value >= 0 ? 'rounded-r' : 'rounded-l'}`}
                style={{
                  background: row.value >= 0 ? positive : negative,
                  width: `${width}%`,
                  [row.value >= 0 ? 'left' : 'right']: '50%',
                }}
              />
            </button>
            <span className="w-20 shrink-0 text-right tabular-nums">{row.text}</span>
          </div>
        )
      })}
    </div>
  )
}

export interface WaterfallRow {
  key: string
  from: number
  to: number
  total: boolean // a bar from zero (start and end), as opposed to a step
  text: string
  onSelect?: () => void
}

/** A bridge from a start value to an end value: totals in the neutral series colour, steps in
 * the blue pole when they add and the red pole when they take away. */
export function Waterfall({
  rows,
  label,
  neutral,
  positive,
  negative,
}: {
  rows: WaterfallRow[]
  label: string
  neutral: string
  positive: string
  negative: string
}) {
  const low = Math.min(0, ...rows.map((r) => Math.min(r.from, r.to)))
  const high = Math.max(1e-9, ...rows.map((r) => Math.max(r.from, r.to)))
  const span = high - low
  const at = (value: number) => ((value - low) / span) * 100
  return (
    <div className="space-y-1" role="group" aria-label={label}>
      {rows.map((row) => {
        const a = at(Math.min(row.from, row.to))
        const b = at(Math.max(row.from, row.to))
        const color = row.total ? neutral : row.to >= row.from ? positive : negative
        return (
          <div key={row.key} className="flex items-center gap-2 text-sm">
            <span className="w-28 shrink-0 truncate" title={row.key}>
              {row.key}
            </span>
            <button
              type="button"
              disabled={!row.onSelect}
              onClick={row.onSelect}
              aria-label={`${row.key}: ${row.text}`}
              title={`${row.key}: ${row.text}`}
              className="relative h-6 flex-1 disabled:cursor-default"
            >
              {low < 0 && (
                <span
                  aria-hidden="true"
                  className="absolute inset-y-0 w-px bg-muted/60"
                  style={{ left: `${at(0)}%` }}
                />
              )}
              <span
                aria-hidden="true"
                className="absolute top-1 h-4 rounded-sm"
                style={{ background: color, left: `${a}%`, width: `${Math.max(b - a, 0.6)}%` }}
              />
            </button>
            <span className="w-24 shrink-0 text-right tabular-nums">{row.text}</span>
          </div>
        )
      })}
    </div>
  )
}

export interface ColumnGroup {
  key: string // x label
  parts: { key: string; value: number; color: string }[]
  onSelect?: () => void
}

/** Stacked columns over time (income by month): at most 24px thick, a 2px gap between parts,
 * one readout line that follows the pointer or keyboard focus. */
export function Columns({
  groups,
  legend,
  label,
  format,
}: {
  groups: ColumnGroup[]
  legend: { key: string; label: string; color: string }[]
  label: string
  format: (value: number) => string
}) {
  const [active, setActive] = useState<string | null>(null)
  const totals = groups.map((g) => g.parts.reduce((sum, p) => sum + p.value, 0))
  const max = Math.max(1e-9, ...totals)
  const ticks = [0, 0.5, 1].map((t) => t * max)
  const every = Math.ceil(groups.length / 12)
  const focus = groups.find((g) => g.key === active)
  return (
    <div className="space-y-1">
      <div className="flex gap-2" role="group" aria-label={label}>
        <div className="flex h-40 flex-col-reverse justify-between text-xs text-muted tabular-nums">
          {ticks.map((t) => (
            <span key={t}>{format(t)}</span>
          ))}
        </div>
        <div className="flex h-40 flex-1 items-end border-b border-border">
          {groups.map((g, n) => {
            const total = totals[n]
            return (
              <button
                key={g.key}
                type="button"
                disabled={!g.onSelect}
                onClick={g.onSelect}
                onPointerEnter={() => setActive(g.key)}
                onPointerLeave={() => setActive(null)}
                onFocus={() => setActive(g.key)}
                onBlur={() => setActive(null)}
                aria-label={`${g.key}: ${g.parts.map((p) => `${p.key} ${format(p.value)}`).join(', ')}`}
                className="flex h-full min-w-0 flex-1 items-end justify-center disabled:cursor-default"
              >
                <span
                  className="flex w-full max-w-6 flex-col-reverse gap-0.5"
                  style={{ height: `${(total / max) * 100}%` }}
                >
                  {g.parts
                    .filter((p) => p.value > 0)
                    .map((p) => (
                      <span
                        key={p.key}
                        className="block rounded-t-sm"
                        style={{ background: p.color, flexGrow: p.value, flexBasis: 0 }}
                      />
                    ))}
                </span>
              </button>
            )
          })}
        </div>
      </div>
      <div className="ml-12 flex text-xs text-muted">
        {groups.map((g, n) => (
          <span key={g.key} className="min-w-0 flex-1 truncate text-center">
            {n % every === 0 ? g.key.slice(2) : ''}
          </span>
        ))}
      </div>
      <p role="status" className="min-h-5 text-sm">
        {focus
          ? `${focus.key}: ${focus.parts.map((p) => `${p.key} ${format(p.value)}`).join(' · ')}`
          : ''}
      </p>
      <Legend items={legend} />
    </div>
  )
}

export function Sparkline({ values, label }: { values: number[]; label: string }) {
  if (values.length < 2) return null
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const points = values.map(
    (v, i) => `${(i / (values.length - 1)) * 100},${28 - ((v - min) / span) * 24}`,
  )
  const [lastX, lastY] = points[points.length - 1].split(',')
  return (
    <svg
      viewBox="0 0 100 32"
      role="img"
      aria-label={label}
      className="h-8 w-full"
      preserveAspectRatio="none"
    >
      <polyline
        points={points.join(' ')}
        fill="none"
        stroke="var(--muted)"
        strokeWidth={1.5}
        vectorEffect="non-scaling-stroke"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      <circle
        cx={lastX}
        cy={lastY}
        r={2.5}
        fill="var(--series-1)"
        stroke="var(--card)"
        strokeWidth={1}
      />
    </svg>
  )
}
