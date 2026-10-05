import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'
import { SIGNS, direction, toNumber } from '../../lib/format'
import { useFormat } from '../../lib/useFormat'
import {
  Columns,
  DivergingBars,
  Waterfall,
  type DivergingRow,
  type WaterfallRow,
} from '../charts/Bars'
import { ChartFrame, DataTable } from '../charts/ChartFrame'
import { SERIES, divergeFill } from '../charts/palette'
import type {
  AttributionData,
  BridgeData,
  CorrelationData,
  HeatmapData,
  IncomeData,
  MonthlyData,
  WidgetProps,
} from '../types'

function lastDay(month: string): string {
  const [y, m] = month.split('-').map(Number)
  return `${month}-${String(new Date(y, m, 0).getDate()).padStart(2, '0')}`
}

const rangeLink = (month: string) => `/transactions?from=${month}-01&to=${lastDay(month)}`

/** The scale of a heatmap: its strongest tone is the largest move shown, at least 5%. */
const reach = (values: (number | null)[], floor: number) =>
  Math.max(floor, ...values.map((v) => Math.abs(v ?? 0)))

function Scale({ max, format }: { max: number; format: (v: number) => string }) {
  return (
    <div className="flex items-center gap-2 text-xs text-muted" aria-hidden="true">
      <span>{format(-max)}</span>
      <span
        className="h-2 flex-1 rounded"
        style={{
          background:
            'linear-gradient(to right, color-mix(in oklab, var(--diverge-neg) 60%, var(--diverge-mid)), var(--diverge-mid), color-mix(in oklab, var(--diverge-pos) 60%, var(--diverge-mid)))',
        }}
      />
      <span>{format(max)}</span>
    </div>
  )
}

export function HeatmapWidget({ data }: WidgetProps<HeatmapData>) {
  const { t } = useTranslation()
  const { pct, eur } = useFormat()
  const navigate = useNavigate()
  if (data.empty) return <p className="text-sm text-muted">{data.reason}</p>
  const cells = data.cells ?? []
  const max = reach(
    cells.map((c) => toNumber(c.twr)),
    0.05,
  )
  return (
    <ChartFrame
      chart={
        <div className="space-y-2">
          <div
            role="group"
            aria-label={t('widgets.returns_heatmap')}
            className="grid grid-cols-[repeat(auto-fill,minmax(110px,1fr))] gap-0.5"
          >
            {cells.map((c) => {
              const v = toNumber(c.twr)
              return (
                <button
                  key={c.instrument_id}
                  type="button"
                  onClick={() => navigate(`/holdings/${c.instrument_id}`)}
                  title={`${c.name}: ${pct(c.twr)}, ${eur(c.pnl_eur)}`}
                  aria-label={`${c.name}: ${pct(c.twr)}`}
                  className="rounded-sm p-2 text-left text-xs"
                  style={{ background: divergeFill(v, max) }}
                >
                  <span className="block truncate font-medium">{c.name}</span>
                  <span className="block tabular-nums">
                    {v === null ? '–' : `${SIGNS[direction(v, 0.00005)]}${pct(Math.abs(v), 1)}`}
                  </span>
                </button>
              )
            })}
          </div>
          <Scale max={max} format={(v) => pct(v, 0)} />
        </div>
      }
      table={
        <DataTable
          caption={t('widgets.returns_heatmap')}
          head={[
            t('widgets.columns.name'),
            t('widgets.return'),
            t('widgets.result'),
            t('widgets.value'),
          ]}
          rows={cells.map((c) => [c.name, pct(c.twr), eur(c.pnl_eur), eur(c.value_eur)])}
        />
      }
    />
  )
}

export function MonthlyReturnsWidget({ data }: WidgetProps<MonthlyData>) {
  const { t } = useTranslation()
  const { pct } = useFormat()
  const navigate = useNavigate()
  if (data.empty) return <p className="text-sm text-muted">{data.reason}</p>
  const years = data.years ?? []
  const max = reach(
    years.flatMap((y) => Object.values(y.months).map((v) => toNumber(v))),
    0.03,
  )
  const monthName = (m: number) => new Date(2000, m - 1, 1).toLocaleString('en', { month: 'short' })
  const table = (
    <table className="w-full text-xs">
      <caption className="sr-only">{t('widgets.monthly_returns')}</caption>
      <thead>
        <tr>
          <th scope="col" className="px-1 py-1 text-left font-medium">
            {t('charts.year')}
          </th>
          {Array.from({ length: 12 }, (_, i) => (
            <th key={i} scope="col" className="px-1 py-1 text-center font-medium">
              {monthName(i + 1)}
            </th>
          ))}
          <th scope="col" className="px-1 py-1 text-center font-medium">
            {t('widgets.year')}
          </th>
        </tr>
      </thead>
      <tbody>
        {years.map((y) => (
          <tr key={y.year}>
            <th scope="row" className="px-1 py-0.5 text-left font-medium">
              {y.year}
            </th>
            {Array.from({ length: 12 }, (_, i) => {
              const raw = y.months[String(i + 1)]
              const v = toNumber(raw)
              const month = `${y.year}-${String(i + 1).padStart(2, '0')}`
              return (
                <td key={i} className="p-0.5">
                  {v === null ? (
                    <span className="block py-1 text-center text-muted">·</span>
                  ) : (
                    <button
                      type="button"
                      onClick={() => navigate(rangeLink(month))}
                      title={`${month}: ${pct(v)}`}
                      aria-label={`${month}: ${pct(v)}`}
                      className="block w-full rounded-sm py-1 text-center tabular-nums"
                      style={{ background: divergeFill(v, max) }}
                    >
                      {SIGNS[direction(v, 0.00005)]}
                      {pct(Math.abs(v), 1)}
                    </button>
                  )}
                </td>
              )
            })}
            <td className="p-0.5 text-center font-medium tabular-nums">{pct(y.total, 1)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
  return (
    <div className="space-y-2 overflow-auto">
      {table}
      <Scale max={max} format={(v) => pct(v, 0)} />
    </div>
  )
}

export function CorrelationWidget({ data }: WidgetProps<CorrelationData>) {
  const { t } = useTranslation()
  const { num } = useFormat()
  const navigate = useNavigate()
  if (data.empty) return <p className="text-sm text-muted">{data.reason}</p>
  const items = data.instruments ?? []
  const values = data.values ?? []
  return (
    <div className="space-y-2 overflow-auto">
      <table className="w-full text-xs">
        <caption className="sr-only">{t('widgets.correlation_matrix')}</caption>
        <thead>
          <tr>
            <td />
            {items.map((i) => (
              <th
                key={i.id}
                scope="col"
                className="max-w-20 truncate px-1 py-1 text-center font-medium"
                title={i.name}
              >
                {i.name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {items.map((row, r) => (
            <tr key={row.id}>
              <th
                scope="row"
                className="max-w-24 truncate px-1 py-0.5 text-left font-medium"
                title={row.name}
              >
                <Link to={`/holdings/${row.id}`}>{row.name}</Link>
              </th>
              {items.map((col, c) => {
                const v = toNumber(values[r]?.[c])
                return (
                  <td key={col.id} className="p-0.5">
                    <button
                      type="button"
                      onClick={() => navigate(`/holdings/${row.id}`)}
                      aria-label={`${row.name} / ${col.name}: ${v === null ? '–' : num(v, 2)}`}
                      className="block w-full rounded-sm py-1 text-center tabular-nums"
                      style={{ background: divergeFill(v, 1) }}
                    >
                      {v === null ? '–' : num(v, 2)}
                    </button>
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <Scale max={1} format={(v) => num(v, 0)} />
      <p className="text-xs text-muted">{t('widgets.correlationNote', { window: data.window })}</p>
    </div>
  )
}

export function BridgeWidget({ data }: WidgetProps<BridgeData>) {
  const { t } = useTranslation()
  const { eur } = useFormat()
  const navigate = useNavigate()
  if (data.empty) return <p className="text-sm text-muted">{data.reason}</p>
  const steps = data.steps ?? []
  const rows: WaterfallRow[] = []
  let current = 0
  for (const s of steps) {
    const amount = Number(s.amount_eur)
    const label =
      s.label === 'start' || s.label === 'end' || s.label === 'contributions'
        ? t(`widgets.bridge.${s.label}`)
        : s.label
    if (s.kind === 'total') {
      rows.push({
        key: label,
        from: 0,
        to: amount,
        total: true,
        text: eur(amount, 0),
        onSelect: () => navigate('/holdings'),
      })
      current = amount
    } else {
      rows.push({
        key: label,
        from: current,
        to: current + amount,
        total: false,
        text: `${SIGNS[direction(amount, 0.5)]}${eur(Math.abs(amount), 0)}`,
        onSelect: () =>
          navigate(
            s.label === 'contributions'
              ? '/transactions'
              : `/holdings?group_by=instrument&value=${encodeURIComponent(s.label)}`,
          ),
      })
      current += amount
    }
  }
  return (
    <ChartFrame
      chart={
        <Waterfall
          rows={rows}
          label={t('widgets.return_bridge')}
          neutral="var(--muted)"
          positive="var(--diverge-pos)"
          negative="var(--diverge-neg)"
        />
      }
      table={
        <DataTable
          caption={t('widgets.return_bridge')}
          head={[t('widgets.step'), t('widgets.amount')]}
          rows={rows.map((r) => [r.key, r.text])}
        />
      }
    />
  )
}

/** What each position added to or took from the return of the period (FR-PF-07). The bars are in
 * percentage points; the table adds the euro amounts, which sum to the portfolio's result. */
export function AttributionWidget({ data }: WidgetProps<AttributionData>) {
  const { t } = useTranslation()
  const { eur, num, pct } = useFormat()
  const navigate = useNavigate()
  if (data.empty) return <p className="text-sm text-muted">{data.reason}</p>
  const rows = data.rows ?? []
  // without a capital base there are no points to show, so the bars fall back to euro
  const inPoints = rows.every((r) => r.points !== null)
  const rowsOut: DivergingRow[] = rows.map((r) => {
    const amount = Number(r.pnl_eur)
    const points = r.points === null ? null : Number(r.points)
    const dir = direction(inPoints ? points : amount, inPoints ? 0.00005 : 0.005)
    return {
      key: r.name,
      value: inPoints ? (points ?? 0) : amount,
      text: inPoints
        ? `${SIGNS[dir]}${num(Math.abs(points ?? 0) * 100, 1)} pp`
        : `${SIGNS[dir]}${eur(Math.abs(amount), 0)}`,
      onSelect:
        r.key === 'other'
          ? undefined
          : () => navigate(`/holdings?group_by=instrument&value=${encodeURIComponent(r.name)}`),
    }
  })
  return (
    <ChartFrame
      chart={
        <div className="space-y-2">
          {data.total_return != null && (
            <p className="text-sm text-muted">
              {t('widgets.attributionTotal', { value: pct(data.total_return, 2) })}
            </p>
          )}
          <DivergingBars
            rows={rowsOut}
            label={t('widgets.attribution')}
            positive="var(--diverge-pos)"
            negative="var(--diverge-neg)"
          />
          <p className="text-xs text-muted">{t('widgets.attributionNote')}</p>
        </div>
      }
      table={
        <DataTable
          caption={t('widgets.attribution')}
          head={[t('widgets.step'), t('widgets.contribution'), t('widgets.points')]}
          rows={rows.map((r) => [
            r.name,
            eur(r.pnl_eur),
            r.points === null ? '–' : `${num(Number(r.points) * 100, 2)} pp`,
          ])}
        />
      }
    />
  )
}

export function IncomeWidget({ data }: WidgetProps<IncomeData>) {
  const { t } = useTranslation()
  const { eur } = useFormat()
  const navigate = useNavigate()
  if (data.empty) return <p className="text-sm text-muted">{data.reason}</p>
  const months = data.months ?? []
  return (
    <ChartFrame
      chart={
        <div className="space-y-1">
          <p className="text-sm text-muted">
            {t('widgets.incomeTotal')}:{' '}
            <strong className="text-foreground">{eur(data.total_eur)}</strong>
          </p>
          <Columns
            groups={months.map((m) => ({
              key: m.month,
              parts: [
                { key: t('widgets.dividends'), value: Number(m.dividends), color: SERIES[0] },
                { key: t('widgets.interest'), value: Number(m.interest), color: SERIES[1] },
              ],
              onSelect: () => navigate(rangeLink(m.month)),
            }))}
            legend={[
              { key: 'd', label: t('widgets.dividends'), color: SERIES[0] },
              { key: 'i', label: t('widgets.interest'), color: SERIES[1] },
            ]}
            label={t('widgets.income')}
            format={(v) => eur(v, 0)}
          />
        </div>
      }
      table={
        <DataTable
          caption={t('widgets.income')}
          head={[t('charts.month'), t('widgets.dividends'), t('widgets.interest')]}
          rows={months.map((m) => [m.month, eur(m.dividends), eur(m.interest)])}
        />
      }
    />
  )
}
