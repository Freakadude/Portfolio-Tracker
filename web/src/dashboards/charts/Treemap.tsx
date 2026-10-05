import { useLayoutEffect, useRef, useState } from 'react'

export interface TreemapItem {
  key: string
  value: number
  weight: number
  color: string
  drillable?: boolean
}

interface Tile {
  item: TreemapItem
  x: number
  y: number
  w: number
  h: number
}

/** Squarified treemap on a width x height box (Bruls, Huijbregts, van Wijk). */
export function squarify(items: TreemapItem[], width: number, height: number): Tile[] {
  const total = items.reduce((sum, i) => sum + i.value, 0)
  if (total <= 0 || width <= 0 || height <= 0) return []
  const scale = (width * height) / total
  const queue = [...items].filter((i) => i.value > 0).sort((a, b) => b.value - a.value)
  const tiles: Tile[] = []
  let x = 0
  let y = 0
  let w = width
  let h = height

  const worst = (row: TreemapItem[], side: number) => {
    const area = row.reduce((sum, i) => sum + i.value * scale, 0)
    const max = Math.max(...row.map((i) => i.value * scale))
    const min = Math.min(...row.map((i) => i.value * scale))
    return Math.max((side * side * max) / (area * area), (area * area) / (side * side * min))
  }
  const place = (row: TreemapItem[], side: number, horizontal: boolean) => {
    const area = row.reduce((sum, i) => sum + i.value * scale, 0)
    const thickness = area / side
    let offset = 0
    for (const item of row) {
      const length = (item.value * scale) / thickness
      tiles.push(
        horizontal
          ? { item, x: x + offset, y, w: length, h: thickness }
          : { item, x, y: y + offset, w: thickness, h: length },
      )
      offset += length
    }
    if (horizontal) {
      y += thickness
      h -= thickness
    } else {
      x += thickness
      w -= thickness
    }
  }

  while (queue.length > 0) {
    const horizontal = w >= h // lay a row along the shorter side
    const side = horizontal ? w : h
    const row = [queue.shift() as TreemapItem]
    while (queue.length > 0 && worst([...row, queue[0]], side) <= worst(row, side)) {
      row.push(queue.shift() as TreemapItem)
    }
    place(row, side, horizontal)
  }
  return tiles
}

/** Part of a whole with many parts: area is value. A label is written only where it fits. */
export function Treemap({
  items,
  format,
  formatWeight,
  label,
  onSelect,
}: {
  items: TreemapItem[]
  format: (value: number) => string
  formatWeight: (weight: number) => string
  label: string
  onSelect?: (key: string) => void
}) {
  const box = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ w: 320, h: 220 })
  useLayoutEffect(() => {
    const el = box.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(([entry]) =>
      setSize({ w: entry.contentRect.width || 320, h: entry.contentRect.height || 220 }),
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [])
  const tiles = squarify(items, size.w, size.h)
  return (
    <div ref={box} role="group" aria-label={label} className="relative h-56 w-full">
      {tiles.map(({ item, x, y, w, h }) => {
        const fits = w > 70 && h > 36
        const interactive = Boolean(onSelect) && item.drillable !== false
        return (
          <button
            key={item.key}
            type="button"
            disabled={!interactive}
            title={`${item.key}: ${formatWeight(item.weight)}, ${format(item.value)}`}
            aria-label={`${item.key}: ${formatWeight(item.weight)}, ${format(item.value)}`}
            onClick={() => onSelect?.(item.key)}
            className="absolute overflow-hidden rounded-sm p-1 text-left text-xs text-white"
            style={{
              left: x,
              top: y,
              width: w,
              height: h,
              background: item.color,
              boxShadow: 'inset 0 0 0 1px var(--card)',
              margin: 0,
            }}
          >
            {fits && (
              <>
                <span className="block truncate font-medium">{item.key}</span>
                <span className="block truncate opacity-90">{formatWeight(item.weight)}</span>
              </>
            )}
          </button>
        )
      })}
    </div>
  )
}
