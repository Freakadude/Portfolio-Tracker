/** The chip that follows the pointer over a line chart: the time, and the value of each series
 * at that time, drawn above the cursor (below it when there is no room above). It uses the page's
 * text and card colours swapped, dark on a light page and light on a dark one, so it stands out
 * from whatever series colour is under it. Built with the DOM because the chart is a canvas. */

export interface TipRow {
  /** The series colour, shown as a small swatch. */
  color?: string
  value: string
  name?: string
}

const GAP = 16 // pixels between the cursor and the chip
const EDGE = 4

/** Classes of the chip element; the colours are set inline because they come from the theme. */
export const TIP_CLASS =
  'pointer-events-none absolute left-0 top-0 z-10 rounded-md px-2.5 py-1.5 text-xs shadow-lg'
export const TIP_STYLE = { background: 'var(--foreground)', color: 'var(--card)' } as const

export function hideTip(box: HTMLElement) {
  box.hidden = true
}

/** Fill the chip and put it above `point`, given in pixels of `host` (the chart's box). */
export function showTip(
  box: HTMLElement,
  host: HTMLElement,
  point: { x: number; y: number },
  when: string,
  rows: TipRow[],
) {
  if (rows.length === 0) {
    hideTip(box)
    return
  }
  box.replaceChildren()
  const time = document.createElement('div')
  time.className = 'text-[11px] opacity-70'
  time.textContent = when
  box.appendChild(time)
  for (const r of rows) {
    const row = document.createElement('div')
    row.className = 'flex items-center gap-2 whitespace-nowrap'
    if (r.color) {
      const swatch = document.createElement('span')
      swatch.style.cssText = `display:inline-block;width:12px;height:3px;border-radius:2px;background:${r.color}`
      row.appendChild(swatch)
    }
    const value = document.createElement('span')
    value.className = 'text-sm font-semibold tabular-nums'
    value.textContent = r.value
    row.appendChild(value)
    if (r.name) {
      const name = document.createElement('span')
      name.className = 'opacity-70'
      name.textContent = r.name
      row.appendChild(name)
    }
    box.appendChild(row)
  }
  box.hidden = false
  const width = box.offsetWidth
  const height = box.offsetHeight
  const left = Math.min(
    Math.max(point.x - width / 2, EDGE),
    Math.max(EDGE, host.clientWidth - width - EDGE),
  )
  const above = point.y - height - GAP
  const top = above >= EDGE ? above : point.y + GAP + 8 // no room above: below the cursor
  box.style.left = `${Math.round(left)}px`
  box.style.top = `${Math.round(top)}px`
}
