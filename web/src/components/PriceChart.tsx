import {
  ColorType,
  LineSeries,
  createChart,
  createSeriesMarkers,
  type SeriesMarker,
  type Time,
} from 'lightweight-charts'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useFormat } from '../lib/useFormat'
import { Button } from './ui'

export interface PricePoint {
  date: string
  close: string
}
export interface TradeMarker {
  date: string
  type: string
}

const RANGES = [
  { key: '1M', days: 31 },
  { key: '3M', days: 92 },
  { key: '1Y', days: 366 },
  { key: 'MAX', days: null },
] as const

function css(name: string, fallback: string) {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

/** The theme can change while the page is open; this changes whenever it does. */
function useThemeKey() {
  const [key, setKey] = useState(0)
  useEffect(() => {
    const bump = () => setKey((k) => k + 1)
    const observer = new MutationObserver(bump)
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme'],
    })
    const media = window.matchMedia?.('(prefers-color-scheme: dark)')
    media?.addEventListener?.('change', bump)
    return () => {
      observer.disconnect()
      media?.removeEventListener?.('change', bump)
    }
  }, [])
  return key
}

/** Markers must sit on a day that has a price; snap each trade to the close on or before it. */
export function snapToPrices(prices: PricePoint[], markers: TradeMarker[]): TradeMarker[] {
  if (prices.length === 0) return []
  const dates = prices.map((p) => p.date)
  return markers.map((m) => {
    let snapped = dates[0]
    for (const d of dates) {
      if (d <= m.date) snapped = d
      else break
    }
    return { ...m, date: snapped }
  })
}

export function PriceChart({
  prices,
  markers,
  label,
}: {
  prices: PricePoint[]
  markers: TradeMarker[]
  label: string
}) {
  const { t } = useTranslation()
  const { eur } = useFormat()
  const container = useRef<HTMLDivElement>(null)
  const [range, setRange] = useState<(typeof RANGES)[number]['key']>('MAX')
  const [asTable, setAsTable] = useState(false)
  const themeKey = useThemeKey()

  useEffect(() => {
    const el = container.current
    if (asTable || !el || prices.length === 0) return
    const text = css('--foreground', '#222')
    const border = css('--border', '#ddd')
    const chart = createChart(el, {
      autoSize: true,
      height: 320,
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: text },
      grid: { vertLines: { color: border }, horzLines: { color: border } },
      rightPriceScale: { borderColor: border },
      timeScale: { borderColor: border },
    })
    const series = chart.addSeries(LineSeries, { color: css('--primary', '#1f4fd6'), lineWidth: 2 })
    series.setData(prices.map((p) => ({ time: p.date as Time, value: Number(p.close) })))
    const gain = css('--gain', '#146c2e')
    const loss = css('--danger', '#b42318')
    const marks: SeriesMarker<Time>[] = snapToPrices(
      prices,
      markers.filter((m) => m.type === 'buy' || m.type === 'sell'),
    )
      .sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0))
      .map((m) =>
        m.type === 'buy'
          ? {
              time: m.date as Time,
              position: 'belowBar',
              shape: 'arrowUp',
              color: gain,
              text: t('position.buy'),
            }
          : {
              time: m.date as Time,
              position: 'aboveBar',
              shape: 'arrowDown',
              color: loss,
              text: t('position.sell'),
            },
      )
    createSeriesMarkers(series, marks)
    const days = RANGES.find((r) => r.key === range)?.days
    if (days) {
      const last = new Date(prices[prices.length - 1].date)
      const from = new Date(last.getTime() - days * 86_400_000).toISOString().slice(0, 10)
      chart
        .timeScale()
        .setVisibleRange({ from: from as Time, to: prices[prices.length - 1].date as Time })
    } else {
      chart.timeScale().fitContent()
    }
    return () => chart.remove()
  }, [prices, markers, range, asTable, themeKey, t])

  const recent = [...prices].reverse()
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        {!asTable &&
          RANGES.map((r) => (
            <Button
              key={r.key}
              variant={range === r.key ? 'primary' : 'secondary'}
              onClick={() => setRange(r.key)}
              aria-pressed={range === r.key}
            >
              {t(`position.chartRanges.${r.key}`)}
            </Button>
          ))}
        <Button variant="ghost" onClick={() => setAsTable((v) => !v)}>
          {t(asTable ? 'position.showChart' : 'position.showTable')}
        </Button>
      </div>
      {asTable ? (
        <div className="max-h-80 overflow-auto">
          <table className="w-full text-sm">
            <caption className="sr-only">{t('position.tableCaption')}</caption>
            <thead>
              <tr className="border-b border-border">
                <th scope="col" className="px-3 py-1 text-left font-medium">
                  {t('priceEntry.date')}
                </th>
                <th scope="col" className="px-3 py-1 text-right font-medium">
                  {t('priceEntry.close')}
                </th>
              </tr>
            </thead>
            <tbody>
              {recent.map((p) => (
                <tr key={p.date} className="border-b border-border">
                  <td className="px-3 py-1">{p.date}</td>
                  <td className="px-3 py-1 text-right tabular-nums">{eur(p.close)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div ref={container} role="img" aria-label={label} className="h-80 w-full" />
      )}
    </div>
  )
}
