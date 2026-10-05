import {
  AreaSeries,
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  LineSeries,
  PriceScaleMode,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type SeriesMarker,
  type SeriesType,
  type Time,
} from 'lightweight-charts'
import { useEffect, useRef } from 'react'
import { Legend } from './ChartFrame'
import { css, useThemeKey } from './theme'

export interface TimeSeries {
  key: string
  label: string
  color: string // a CSS variable, resolved when drawn
  points: { time: string; value: number }[]
  kind?: 'line' | 'area'
}

export interface Candle {
  time: string
  open: number
  high: number
  low: number
  close: number
}

export interface Marker {
  time: string
  position: 'aboveBar' | 'belowBar'
  shape: 'arrowUp' | 'arrowDown'
  text: string
  color: string
}

/** The value of a CSS variable written as var(--name), resolved for the canvas. */
function resolve(color: string): string {
  const match = color.match(/^var\((--[\w-]+)\)$/)
  return match ? css(match[1], '#2a78d6') : color
}

function withAlpha(hex: string, alpha: number): string {
  const m = hex.match(/^#([0-9a-f]{6})$/i)
  if (!m) return hex
  const n = parseInt(m[1], 16)
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`
}

/** Lines, areas, candles and volume against time, with a crosshair that reads every series at
 * the date under the pointer and a legend for two or more. */
export function TimeChart({
  series,
  candles,
  volume,
  markers,
  label,
  height,
  logScale = false,
  format,
  onTimeClick,
}: {
  series: TimeSeries[]
  candles?: Candle[]
  volume?: { time: string; value: number }[]
  markers?: Marker[]
  label: string
  /** A fixed height in pixels; by default the chart fills the room its widget has. */
  height?: number
  logScale?: boolean
  format: (value: number) => string
  onTimeClick?: (time: string) => void
}) {
  const container = useRef<HTMLDivElement>(null)
  const tooltip = useRef<HTMLDivElement>(null)
  const themeKey = useThemeKey()

  useEffect(() => {
    const el = container.current
    if (!el || (series.every((s) => s.points.length === 0) && !candles?.length)) return
    const text = css('--foreground', '#222')
    const grid = css('--chart-grid', '#e6e8ec')
    const surface = css('--card', '#fff')
    const chart: IChartApi = createChart(el, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: text,
        panes: { separatorColor: grid },
      },
      grid: { vertLines: { color: grid }, horzLines: { color: grid } },
      rightPriceScale: {
        borderColor: grid,
        mode: logScale ? PriceScaleMode.Logarithmic : PriceScaleMode.Normal,
      },
      timeScale: { borderColor: grid },
      localization: { priceFormatter: format },
    })
    const drawn: { api: ISeriesApi<SeriesType>; label: string; color: string }[] = []

    for (const s of series) {
      const color = resolve(s.color)
      const api =
        s.kind === 'area'
          ? chart.addSeries(AreaSeries, {
              lineColor: color,
              topColor: withAlpha(color, 0.12),
              bottomColor: withAlpha(color, 0),
              lineWidth: 2,
              priceLineVisible: false,
              lastValueVisible: false,
            })
          : chart.addSeries(LineSeries, {
              color,
              lineWidth: 2,
              priceLineVisible: false,
              lastValueVisible: false,
              crosshairMarkerRadius: 4,
              crosshairMarkerBorderColor: surface,
            })
      api.setData(s.points.map((p) => ({ time: p.time as Time, value: p.value })))
      drawn.push({ api, label: s.label, color })
    }
    if (candles?.length) {
      const up = resolve('var(--diverge-pos)')
      const down = resolve('var(--diverge-neg)')
      const api = chart.addSeries(CandlestickSeries, {
        upColor: up,
        downColor: down,
        borderUpColor: up,
        borderDownColor: down,
        wickUpColor: up,
        wickDownColor: down,
        priceLineVisible: false,
        lastValueVisible: false,
      })
      api.setData(candles.map((c) => ({ ...c, time: c.time as Time })))
      drawn.push({ api, label: '', color: up })
    }
    if (volume?.length) {
      const bars = chart.addSeries(
        HistogramSeries,
        {
          color: withAlpha(resolve('var(--muted)'), 0.5),
          priceFormat: { type: 'volume' },
          priceLineVisible: false,
          lastValueVisible: false,
        },
        1, // its own pane below the prices: one axis per pane, never two on one plot
      )
      bars.setData(volume.map((v) => ({ time: v.time as Time, value: v.value })))
    }
    if (markers?.length && drawn[0]) {
      createSeriesMarkers(
        drawn[0].api,
        [...markers]
          .sort((a, b) => (a.time < b.time ? -1 : a.time > b.time ? 1 : 0))
          .map((m): SeriesMarker<Time> => ({
            time: m.time as Time,
            position: m.position,
            shape: m.shape,
            text: m.text,
            color: resolve(m.color),
          })),
      )
    }
    chart.timeScale().fitContent()

    const box = tooltip.current
    chart.subscribeCrosshairMove((param) => {
      if (!box) return
      if (!param.time || !param.point || param.point.x < 0) {
        box.hidden = true
        return
      }
      box.replaceChildren()
      const when = document.createElement('div')
      when.className = 'font-medium'
      when.textContent = String(param.time)
      box.appendChild(when)
      for (const d of drawn) {
        const value = param.seriesData.get(d.api) as { value?: number; close?: number } | undefined
        const number = value?.value ?? value?.close
        if (number === undefined) continue
        const row = document.createElement('div')
        row.className = 'flex items-center gap-2'
        const key = document.createElement('span')
        key.style.cssText = `display:inline-block;width:12px;height:3px;background:${d.color}`
        const amount = document.createElement('span')
        amount.className = 'font-semibold'
        amount.textContent = format(number)
        row.append(key, amount)
        if (d.label) {
          const name = document.createElement('span')
          name.className = 'text-muted'
          name.textContent = d.label
          row.appendChild(name)
        }
        box.appendChild(row)
      }
      box.hidden = false
    })
    if (onTimeClick) {
      chart.subscribeClick((param) => {
        if (param.time) onTimeClick(String(param.time))
      })
    }
    return () => chart.remove()
  }, [series, candles, volume, markers, height, logScale, format, onTimeClick, themeKey])

  return (
    <div className="flex h-full min-h-48 flex-col gap-1">
      <div
        className="relative min-h-0 flex-1"
        style={height ? { height, flex: 'none' } : undefined}
      >
        <div ref={container} role="img" aria-label={label} className="h-full w-full" />
        <div
          ref={tooltip}
          hidden
          className="pointer-events-none absolute left-2 top-2 z-10 space-y-0.5 rounded border border-border bg-card px-2 py-1 text-xs shadow"
        />
      </div>
      <Legend items={series.map((s) => ({ key: s.key, label: s.label, color: s.color }))} />
    </div>
  )
}
