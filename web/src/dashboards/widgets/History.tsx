import { useCallback, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'
import { toNumber } from '../../lib/format'
import { useFormat } from '../../lib/useFormat'
import { ChartFrame, DataTable } from '../charts/ChartFrame'
import { SERIES } from '../charts/palette'
import { TimeChart, type ChartTime, type Marker, type TimeSeries } from '../charts/TimeChart'
import type {
  DrawdownData,
  PerformanceData,
  PriceChartData,
  ValueHistoryData,
  WidgetProps,
} from '../types'

const n = (v: string | null | undefined) => toNumber(v) ?? 0

/** Clicking a point on a chart over time opens the transactions up to that date. */
export function useDateDrill() {
  const navigate = useNavigate()
  // stable, so a chart is not redrawn (and its zoom lost) every time its widget renders
  return useCallback((date: string) => navigate(`/transactions?to=${date}`), [navigate])
}

export function ValueHistoryWidget({ data }: WidgetProps<ValueHistoryData>) {
  const { t } = useTranslation()
  const { eur } = useFormat()
  const drill = useDateDrill()
  const format = useMemo(() => (v: number) => eur(v, 0), [eur])
  const points = useMemo(() => data.points ?? [], [data.points])
  const series: TimeSeries[] = useMemo(
    () => [
      {
        key: 'value',
        label: t('widgets.value'),
        color: SERIES[0],
        kind: 'area',
        points: points.map((p) => ({ time: p.date, value: n(p.value) })),
      },
      {
        key: 'contributions',
        label: t('widgets.contributions'),
        color: SERIES[1],
        points: points.map((p) => ({ time: p.date, value: n(p.net_contributions) })),
      },
    ],
    [points, t],
  )
  if (data.empty) return <p className="text-sm text-muted">{data.reason}</p>
  return (
    <div className="flex h-full flex-col gap-1">
      <p className="text-xs text-muted">
        {t('widgets.historyRange', { start: data.start, end: data.end, period: data.period })}
        {data.unpriced_before && (
          <> {t('widgets.historyUnpricedBefore', { date: data.unpriced_before })}</>
        )}
        {!!data.unpriced_days && (
          <> {t('widgets.historyUnpricedDays', { count: data.unpriced_days })}</>
        )}
      </p>
      <ChartFrame
        chart={
          <TimeChart
            series={series}
            label={t('widgets.value_history')}
            format={format}
            logScale={data.log_scale}
            onTimeClick={drill}
          />
        }
        table={
          <DataTable
            caption={t('widgets.value_history')}
            head={[t('charts.date'), t('widgets.value'), t('widgets.contributions')]}
            rows={[...points]
              .reverse()
              .map((p) => [p.date, eur(p.value), eur(p.net_contributions)])}
          />
        }
      />
    </div>
  )
}

export function DrawdownWidget({ data }: WidgetProps<DrawdownData>) {
  const { t } = useTranslation()
  const { pct } = useFormat()
  const drill = useDateDrill()
  const points = useMemo(() => data.points ?? [], [data.points])
  const format = useMemo(() => (v: number) => pct(v, 1), [pct])
  const series: TimeSeries[] = useMemo(
    () => [
      {
        key: 'drawdown',
        label: t('widgets.drawdown'),
        color: 'var(--diverge-neg)',
        kind: 'area',
        points: points.map((p) => ({ time: p.date, value: n(p.value) })),
      },
    ],
    [points, t],
  )
  if (data.empty) return <p className="text-sm text-muted">{data.reason}</p>
  return (
    <div className="flex h-full flex-col gap-2">
      <p className="text-sm text-muted">
        {t('widgets.maxDrawdown')}:{' '}
        <strong className="text-foreground">{pct(data.max_drawdown, 1)}</strong>
        {' · '}
        {t('widgets.currentDrawdown')}:{' '}
        <strong className="text-foreground">{pct(data.current_drawdown, 1)}</strong>
      </p>
      <ChartFrame
        chart={
          <TimeChart
            series={series}
            label={t('widgets.drawdown')}
            format={format}
            onTimeClick={drill}
          />
        }
        table={
          <DataTable
            caption={t('widgets.drawdown')}
            head={[t('charts.date'), t('widgets.drawdown')]}
            rows={[...points].reverse().map((p) => [p.date, pct(p.value, 1)])}
          />
        }
      />
    </div>
  )
}

export function PerformanceWidget({ data }: WidgetProps<PerformanceData>) {
  const { t } = useTranslation()
  const { num } = useFormat()
  const navigate = useNavigate()
  const format = useMemo(() => (v: number) => num(v, 1), [num])
  const all = useMemo(() => data.series ?? [], [data.series])
  const series: TimeSeries[] = useMemo(
    () =>
      all.map((s, i) => ({
        key: s.key,
        label: s.label,
        color: SERIES[i % SERIES.length],
        points: s.points.map((p) => ({ time: p.date, value: n(p.value) })),
      })),
    [all],
  )
  if (data.empty) return <p className="text-sm text-muted">{data.reason}</p>
  const dates = all[0]?.points.map((p) => p.date) ?? []
  return (
    <div className="flex h-full flex-col gap-2">
      <p className="text-xs text-muted">{t('widgets.rebased')}</p>
      {data.suggest_benchmark && (
        <p className="text-xs text-muted">
          {t('widgets.benchmarkHint')}{' '}
          <Link to="/holdings" className="underline">
            {t('widgets.benchmarkHintLink')}
          </Link>
        </p>
      )}
      <ChartFrame
        chart={
          <TimeChart
            series={series}
            label={t('widgets.performance_comparison')}
            format={format}
            onTimeClick={(d) => navigate(`/transactions?to=${d}`)}
          />
        }
        table={
          <DataTable
            caption={t('widgets.performance_comparison')}
            head={[t('charts.date'), ...all.map((s) => s.label)]}
            rows={[...dates]
              .reverse()
              .map((date) => [
                date,
                ...all.map((s) => num(s.points.find((p) => p.date === date)?.value, 1)),
              ])}
          />
        }
      />
    </div>
  )
}

/** Seconds on the clock of the exchange for an intraday point such as 2024-01-12T09:15:00. The
 * chart reads them as UTC, so the axis shows market hours whatever zone the browser is in. */
const clockSeconds = (date: string) => Date.parse(`${date}Z`) / 1000

const clockLabel = (time: ChartTime) =>
  typeof time === 'number' ? new Date(time * 1000).toISOString().slice(11, 16) : String(time)

export function PriceChartWidget({ data, config }: WidgetProps<PriceChartData>) {
  const { t } = useTranslation()
  const { num } = useFormat()
  const navigate = useNavigate()
  const format = useMemo(() => (v: number) => num(v, 2), [num])
  const percent = useMemo(() => (v: number) => `${num(v, 2)}%`, [num])
  const intraday = data.intraday === true
  const showPrice = data.show_price !== false
  const points = useMemo(() => data.points ?? [], [data.points])
  const when = useCallback(
    (date: string): ChartTime => (intraday ? clockSeconds(date) : date),
    [intraday],
  )
  const overlays = useMemo(() => (config.overlays as string[] | undefined) ?? [], [config.overlays])
  const showVolume = showPrice && !intraday && overlays.includes('volume')
  // each thing with its own scale gets its own pane, counted from the top
  const panes = useMemo(() => {
    let next = showPrice ? 1 : 0
    const changes = data.changes ? next++ : undefined
    const since = data.since_start ? next++ : undefined
    return { changes, since, volume: next }
  }, [showPrice, data.changes, data.since_start])
  const series: TimeSeries[] = useMemo(() => {
    const list: TimeSeries[] = []
    if (showPrice && data.chart !== 'candles') {
      list.push({
        key: 'close',
        label: data.name ?? t('widgets.price'),
        color: SERIES[0],
        points: points.map((p) => ({ time: when(p.date), value: n(p.close) })),
      })
    }
    if (showPrice && data.ma50) {
      list.push({
        key: 'ma50',
        label: t('widgets.ma50'),
        color: SERIES[1],
        points: data.ma50.map((p) => ({ time: when(p.date), value: n(p.value) })),
      })
    }
    if (showPrice && data.ma200) {
      list.push({
        key: 'ma200',
        label: t('widgets.ma200'),
        color: SERIES[2],
        points: data.ma200.map((p) => ({ time: when(p.date), value: n(p.value) })),
      })
    }
    if (data.changes && panes.changes !== undefined) {
      list.push({
        key: 'changes',
        label: t(intraday ? 'widgets.changesPerRefresh' : 'widgets.changesPerDay'),
        color: SERIES[3],
        kind: 'bars',
        pane: panes.changes,
        format: percent,
        points: data.changes.map((p) => ({ time: when(p.date), value: n(p.value) })),
      })
    }
    if (data.since_start && panes.since !== undefined) {
      list.push({
        key: 'since_start',
        label: t('widgets.sinceStart'),
        color: SERIES[4],
        pane: panes.since,
        format: percent,
        points: data.since_start.map((p) => ({ time: when(p.date), value: n(p.value) })),
      })
    }
    return list
  }, [data, points, panes, showPrice, intraday, percent, when, t])
  const candles = useMemo(
    () =>
      showPrice && data.chart === 'candles'
        ? points.map((p) => ({
            time: p.date,
            open: n(p.open ?? p.close),
            high: n(p.high ?? p.close),
            low: n(p.low ?? p.close),
            close: n(p.close),
          }))
        : undefined,
    [showPrice, data.chart, points],
  )
  const volume = useMemo(
    () =>
      showVolume
        ? points.filter((p) => p.volume !== null).map((p) => ({ time: p.date, value: n(p.volume) }))
        : undefined,
    [showVolume, points],
  )
  const markers: Marker[] = useMemo(
    () =>
      showPrice
        ? (data.trades ?? []).map((tr) =>
            tr.type === 'buy'
              ? {
                  time: tr.date,
                  position: 'belowBar',
                  shape: 'arrowUp',
                  text: t('position.buy'),
                  color: 'var(--diverge-pos)',
                }
              : {
                  time: tr.date,
                  position: 'aboveBar',
                  shape: 'arrowDown',
                  text: t('position.sell'),
                  color: 'var(--diverge-neg)',
                },
          )
        : [],
    [showPrice, data.trades, t],
  )
  if (data.empty) return <p className="text-sm text-muted">{data.reason}</p>
  const changeAt = new Map((data.changes ?? []).map((c) => [c.date, c.value]))
  const sinceAt = new Map((data.since_start ?? []).map((c) => [c.date, c.value]))
  // the table lists every point the chart draws; with the price left out, the days that have
  // a change
  const tableDates = showPrice
    ? points.map((p) => p.date)
    : [...new Set([...changeAt.keys(), ...sinceAt.keys()])].sort()
  const closeAt = new Map(points.map((p) => [p.date, p.close]))
  const head = [
    t(intraday ? 'charts.time' : 'charts.date'),
    ...(showPrice ? [t(intraday ? 'widgets.price' : 'widgets.close')] : []),
    ...(data.changes ? [t(intraday ? 'widgets.changesPerRefresh' : 'widgets.changesPerDay')] : []),
    ...(data.since_start ? [t('widgets.sinceStart')] : []),
  ]
  const cell = (v: string | undefined) => (v === undefined ? '' : `${num(v, 2)}%`)
  const session = intraday
    ? [
        t('widgets.sessionOf', { date: data.session_date }),
        data.previous_close
          ? t('widgets.previousClose', { price: num(data.previous_close, 2) })
          : null,
      ]
        .filter(Boolean)
        .join(' · ')
    : ''
  return (
    <div className="flex h-full flex-col gap-1">
      <p className="text-sm text-muted">
        {data.name} · {data.currency}
        {session && ` · ${session}`}
      </p>
      <ChartFrame
        chart={
          <TimeChart
            series={series}
            candles={candles}
            volume={volume}
            volumePane={panes.volume}
            intraday={intraday}
            timeLabel={intraday ? clockLabel : undefined}
            markers={snapMarkers(
              markers,
              points.map((p) => p.date),
            )}
            label={`${t('widgets.price_chart')}: ${data.name}`}
            format={format}
            onTimeClick={() => data.instrument_id && navigate(`/holdings/${data.instrument_id}`)}
          />
        }
        table={
          <DataTable
            caption={t('widgets.price_chart')}
            head={head}
            rows={[...tableDates]
              .reverse()
              .map((date) => [
                intraday ? date.slice(11, 16) : date,
                ...(showPrice ? [num(closeAt.get(date), 2)] : []),
                ...(data.changes ? [cell(changeAt.get(date))] : []),
                ...(data.since_start ? [cell(sinceAt.get(date))] : []),
              ])}
          />
        }
      />
    </div>
  )
}

/** A marker must sit on a day that has a price: move each to the close on or before it. */
function snapMarkers(markers: Marker[], dates: string[]): Marker[] {
  if (dates.length === 0) return []
  return markers.map((m) => {
    let snapped = dates[0]
    for (const d of dates) {
      if (d <= m.time) snapped = d
      else break
    }
    return { ...m, time: snapped }
  })
}
