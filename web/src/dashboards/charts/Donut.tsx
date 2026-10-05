import { useState } from 'react'
import { Legend } from './ChartFrame'

export interface DonutSlice {
  key: string
  value: number
  weight: number
  color: string
  drillable?: boolean
}

const CENTER = 100
const OUTER = 88
const INNER = 58

function point(angle: number, radius: number): [number, number] {
  return [CENTER + radius * Math.sin(angle), CENTER - radius * Math.cos(angle)]
}

function arc(from: number, to: number): string {
  const full = to - from >= Math.PI * 2 - 1e-6
  const end = full ? from + Math.PI * 2 - 1e-4 : to
  const [x1, y1] = point(from, OUTER)
  const [x2, y2] = point(end, OUTER)
  const [x3, y3] = point(end, INNER)
  const [x4, y4] = point(from, INNER)
  const large = end - from > Math.PI ? 1 : 0
  return `M${x1} ${y1} A${OUTER} ${OUTER} 0 ${large} 1 ${x2} ${y2} L${x3} ${y3} A${INNER} ${INNER} 0 ${large} 0 ${x4} ${y4} Z`
}

/** Part of a whole. At most six slices (the rest are folded into "Other" by the caller); a gap
 * in the surface colour separates them, and the centre reads out the total or the slice under
 * the pointer or keyboard focus. */
export function Donut({
  slices,
  centerLabel,
  format,
  formatWeight,
  label,
  onSelect,
}: {
  slices: DonutSlice[]
  centerLabel: string
  format: (value: number) => string
  formatWeight: (weight: number) => string
  label: string
  onSelect?: (key: string) => void
}) {
  const [active, setActive] = useState<string | null>(null)
  const shown = slices.filter((s) => s.weight > 0)
  let angle = 0
  const arcs = shown.map((s) => {
    const from = angle
    angle += s.weight * Math.PI * 2
    return { slice: s, from, to: angle }
  })
  const focus = shown.find((s) => s.key === active)
  return (
    <div className="flex flex-col items-center gap-3">
      <div className="relative w-full max-w-[220px]">
        <svg viewBox="0 0 200 200" role="group" aria-label={label} className="w-full">
          {arcs.map(({ slice, from, to }) => {
            const interactive = Boolean(onSelect) && slice.drillable !== false
            return (
              <path
                key={slice.key}
                d={arc(from, to)}
                fill={slice.color}
                stroke="var(--card)"
                strokeWidth={2}
                opacity={active && active !== slice.key ? 0.55 : 1}
                tabIndex={0}
                role={interactive ? 'button' : 'img'}
                aria-label={`${slice.key}: ${formatWeight(slice.weight)}, ${format(slice.value)}`}
                className={interactive ? 'cursor-pointer' : undefined}
                onPointerEnter={() => setActive(slice.key)}
                onPointerLeave={() => setActive(null)}
                onFocus={() => setActive(slice.key)}
                onBlur={() => setActive(null)}
                onClick={() => interactive && onSelect?.(slice.key)}
                onKeyDown={(e) => {
                  if (interactive && (e.key === 'Enter' || e.key === ' ')) {
                    e.preventDefault()
                    onSelect?.(slice.key)
                  }
                }}
              />
            )
          })}
        </svg>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center text-center">
          <span className="max-w-[90px] truncate text-xs text-muted">
            {focus ? focus.key : centerLabel}
          </span>
          <span className="text-lg font-semibold [font-variant-numeric:normal]">
            {focus ? format(focus.value) : format(shown.reduce((sum, s) => sum + s.value, 0))}
          </span>
          {focus && <span className="text-xs text-muted">{formatWeight(focus.weight)}</span>}
        </div>
      </div>
      <Legend
        items={shown.map((s) => ({
          key: s.key,
          label: `${s.key} ${formatWeight(s.weight)}`,
          color: s.color,
        }))}
      />
    </div>
  )
}
