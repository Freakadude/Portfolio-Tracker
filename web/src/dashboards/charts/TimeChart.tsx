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

/** A moment on the time axis: a date, or seconds of the clock shown (an intraday chart). */
export type ChartTime = string | number

export interface TimeSeries {
  key: string
  label: string
  color: string // a CSS variable, resolved when drawn
  points: { time: ChartTime; value: number }[]
  // band: a tinted area down to the axis; mask: an area in the card colour drawn over it, so
  // that what is left is the band between the two (a 10th to 90th percentile range); bars:
  // columns coloured by sign, for changes
  kind?: 'line' | 'area' | 'band' | 'mask' | 'bars'
  /** The pane it is drawn in, counted from the top (default 0). A pane has one axis. */
  pane?: number
  /** How its values are written on the axis and in the tooltip (default: the chart's format). */
  format?: (value: number) => string
}

export interface Candle {
  time: ChartTime
  open: number
  high: number
  low: number
  close: number
}

export interface Marker {
  time: ChartTime
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
  intraday = false,
  volumePane = 1,
  format,
  timeLabel = String,
  onTimeClick,
}: {
  series: TimeSeries[]
  candles?: Candle[]
  volume?: { time: ChartTime; value: number }[]
  markers?: Marker[]
  label: string
  /** A fixed height in pixels; by default the chart fills the room its widget has. */
  height?: number
  logScale?: boolean
  /** Times are of one day: the axis shows the clock. */
  intraday?: boolean
  volumePane?: number
  format: (value: number) => string
  /** How the time under the pointer is written in the tooltip. */
  timeLabel?: (time: ChartTime) => string
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
      timeScale: { borderColor: grid, timeVisible: intraday, secondsVisible: false },
      localization: { priceFormatter: format },
    })
    const drawn: {
      api: ISeriesApi<SeriesType>
      label: string
      color: string
      format?: (value: number) => string
    }[] = []

    for (const s of series) {
      const color = resolve(s.color)
      const pane = s.pane ?? 0
      const own = s.format
        ? { priceFormat: { type: 'custom' as const, formatter: s.format, minMove: 0.01 } }
        : {}
      const shared = { priceLineVisible: false, lastValueVisible: false, ...own }
      const api =
        s.kind === 'bars'
          ? chart.addSeries(HistogramSeries, shared, pane)
          : s.kind === 'band' || s.kind === 'mask'
            ? chart.addSeries(
                AreaSeries,
                {
                  ...shared,
                  lineColor: color,
                  topColor: s.kind === 'band' ? withAlpha(color, 0.22) : surface,
                  bottomColor: s.kind === 'band' ? withAlpha(color, 0.22) : surface,
                  lineWidth: 1,
                },
                pane,
              )
            : s.kind === 'area'
              ? chart.addSeries(
                  AreaSeries,
                  {
                    ...shared,
                    lineColor: color,
                    topColor: withAlpha(color, 0.12),
                    bottomColor: withAlpha(color, 0),
                    lineWidth: 2,
                  },
                  pane,
                )
              : chart.addSeries(
                  LineSeries,
                  {
                    ...shared,
                    color,
                    lineWidth: 2,
                    crosshairMarkerRadius: 4,
                    crosshairMarkerBorderColor: surface,
                  },
                  pane,
                )
      const up = resolve('var(--diverge-pos)')
      const down = resolve('var(--diverge-neg)')
      api.setData(
        s.points.map((p) =>
          s.kind === 'bars'
            ? { time: p.time as Time, value: p.value, color: p.value >= 0 ? up : down }
            : { time: p.time as Time, value: p.value },
        ),
      )
      drawn.push({ api, label: s.label, color, format: s.format })
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
        volumePane, // its own pane below the prices: one axis per pane, never two on one plot
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
    const panes = Math.max(0, volume?.length ? volumePane : 0, ...series.map((s) => s.pane ?? 0))
    if (panes > 0) chart.panes()[0]?.setStretchFactor(3) // the first pane is the main one
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
      when.textContent = timeLabel(param.time as ChartTime)
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
        amount.textContent = (d.format ?? format)(number)
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
  }, [
    series,
    candles,
    volume,
    markers,
    height,
    logScale,
    intraday,
    volumePane,
    format,
    timeLabel,
    onTimeClick,
    themeKey,
  ])

  return (
    <div className="flex h-full min-h-48 flex-col gap-1">
      <div
        className="relative min-h-48 flex-1"
        style={height ? { height, flex: 'none' } : undefined}
      >
        {/* Out of the flow: a chart that sizes itself to this box must never be able to make the
            box bigger, or in a box without a fixed height (the settings preview) it grows for
            ever. */}
        <div ref={container} role="img" aria-label={label} className="absolute inset-0" />
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
