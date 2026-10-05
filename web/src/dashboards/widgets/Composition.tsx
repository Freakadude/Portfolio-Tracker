import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'
import { Delta } from '../../components/display'
import { ARROWS, SIGNS, direction, toNumber } from '../../lib/format'
import { useFormat } from '../../lib/useFormat'
import { DivergingBars, type DivergingRow } from '../charts/Bars'
import { ChartFrame, DataTable } from '../charts/ChartFrame'
import { Donut, type DonutSlice } from '../charts/Donut'
import { OTHER, colorOf, foldTail } from '../charts/palette'
import { Treemap, type TreemapItem } from '../charts/Treemap'
import type { AllocationData, DriftData, HoldingsData, WidgetProps } from '../types'

/** The holdings list a slice opens (FR-DB-06). */
export const holdingsFilter = (groupBy: string, value: string) =>
  `/holdings?group_by=${encodeURIComponent(groupBy)}&value=${encodeURIComponent(value)}`

/** A difference between two shares, in percentage points, with sign and arrow. */
export function Points({ value }: { value: string | number | null | undefined }) {
  const { num } = useFormat()
  const n = toNumber(value)
  if (n === null) return <span className="text-muted">–</span>
  const dir = direction(n, 0.00005)
  return (
    <span className="whitespace-nowrap tabular-nums">
      {SIGNS[dir]}
      {num(Math.abs(n) * 100, 1)} pp <span aria-hidden="true">{ARROWS[dir]}</span>
    </span>
  )
}

export function AllocationWidget({ data }: WidgetProps<AllocationData>) {
  const { t } = useTranslation()
  const { eur, pct } = useFormat()
  const navigate = useNavigate()
  const slices = useMemo(() => data.slices ?? [], [data.slices])
  const groupBy = data.group_by ?? 'asset_class'
  const items = useMemo(() => {
    const base = slices.map((s) => ({
      key: s.key,
      value: Number(s.value_eur),
      weight: Number(s.weight),
    }))
    const limit = data.chart === 'treemap' ? 15 : 6
    return foldTail(base, limit, (rest, value) => ({
      key: OTHER,
      value,
      weight: rest.reduce((sum, r) => sum + r.weight, 0),
    }))
  }, [slices, data.chart])
  const keys = useMemo(() => items.map((i) => i.key), [items])
  const drill = (key: string) => key !== OTHER && navigate(holdingsFilter(groupBy, key))
  if (data.unavailable || data.empty) {
    return (
      <div className="space-y-1">
        <p className="text-sm text-muted">{data.reason}</p>
        {(data.unvalued ?? 0) > 0 && (
          <p className="text-sm">{t('overview.unvalued', { count: data.unvalued })}</p>
        )}
      </div>
    )
  }
  const withTargets = data.show_target && slices.some((s) => s.target !== null)
  const colored = items.map((i) => ({
    ...i,
    color: colorOf(keys, i.key),
    drillable: i.key !== OTHER,
  }))
  return (
    <div className="flex h-full flex-col gap-3">
      <ChartFrame
        chart={
          data.chart === 'treemap' ? (
            <Treemap
              items={colored as TreemapItem[]}
              format={(v) => eur(v, 0)}
              formatWeight={(w) => pct(w, 1)}
              label={t('widgets.allocation')}
              onSelect={drill}
            />
          ) : (
            <Donut
              slices={colored as DonutSlice[]}
              centerLabel={t('widgets.total')}
              format={(v) => eur(v, 0)}
              formatWeight={(w) => pct(w, 1)}
              label={t('widgets.allocation')}
              onSelect={drill}
            />
          )
        }
        table={
          <DataTable
            caption={t('widgets.allocation')}
            head={[
              t(`widgets.groups.${groupBy}`),
              t('widgets.value'),
              t('widgets.weight'),
              t('widgets.target'),
              t('widgets.drift'),
            ]}
            rows={slices.map((s) => [
              s.key,
              eur(s.value_eur, 0),
              pct(s.weight, 1),
              s.target === null ? '–' : pct(s.target, 1),
              <Points key="d" value={s.drift_pp} />,
            ])}
          />
        }
      />
      {withTargets && (
        <ul className="space-y-0.5 text-xs">
          {slices
            .filter((s) => s.target !== null)
            .map((s) => (
              <li key={s.key} className="flex justify-between gap-2">
                <span className="truncate">{s.key}</span>
                <span className="tabular-nums text-muted">
                  {pct(s.weight, 1)} / {pct(s.target, 1)} <Points value={s.drift_pp} />
                  {s.outside_band && (
                    <span className="ml-1 font-medium text-danger">{t('widgets.outsideBand')}</span>
                  )}
                </span>
              </li>
            ))}
        </ul>
      )}
      {(data.unvalued ?? 0) > 0 && (
        <p className="text-xs text-muted">{t('overview.unvalued', { count: data.unvalued })}</p>
      )}
    </div>
  )
}

export function DriftBarsWidget({ data }: WidgetProps<DriftData>) {
  const { t } = useTranslation()
  const { pct } = useFormat()
  const navigate = useNavigate()
  if (data.empty) return <p className="text-sm text-muted">{data.reason}</p>
  const bars = data.bars ?? []
  const rows: DivergingRow[] = bars.map((b) => ({
    key: b.key,
    value: Number(b.drift_pp),
    band: b.band === null ? null : Number(b.band),
    text: `${SIGNS[direction(b.drift_pp, 0.00005)]}${(Math.abs(Number(b.drift_pp)) * 100).toFixed(1)} pp${b.outside_band ? ' !' : ''}`,
    onSelect: () => navigate(holdingsFilter('sleeve', b.key)),
  }))
  return (
    <ChartFrame
      chart={
        <div className="space-y-2">
          <DivergingBars
            rows={rows}
            label={t('widgets.drift_bars')}
            positive="var(--diverge-pos)"
            negative="var(--diverge-neg)"
          />
          <p className="text-xs text-muted">{t('widgets.driftNote')}</p>
        </div>
      }
      table={
        <DataTable
          caption={t('widgets.drift_bars')}
          head={[
            t('widgets.groups.sleeve'),
            t('widgets.weight'),
            t('widgets.target'),
            t('widgets.drift'),
            t('widgets.band'),
          ]}
          rows={bars.map((b) => [
            b.key,
            pct(b.weight, 1),
            pct(b.target, 1),
            <Points key="d" value={b.drift_pp} />,
            b.band === null ? '–' : `± ${(Number(b.band) * 100).toFixed(1)} pp`,
          ])}
        />
      }
    />
  )
}

const COLUMN_KEYS = [
  'name',
  'account',
  'quantity',
  'close',
  'value',
  'weight',
  'unrealized',
  'day',
  'income',
  'total_return',
] as const

export function HoldingsTableWidget({ data, config }: WidgetProps<HoldingsData>) {
  const { t } = useTranslation()
  const { eur, qty, pct } = useFormat()
  const rows = useMemo(() => data.rows ?? [], [data.rows])
  const groupBy = (config.group_by as string | undefined) ?? data.group_by ?? 'none'
  const columns = (
    (data.columns ?? ['name', 'quantity', 'value', 'weight', 'unrealized', 'day']) as string[]
  ).filter((c) => (COLUMN_KEYS as readonly string[]).includes(c))
  const groups = useMemo(() => {
    const out = new Map<string, typeof rows>()
    for (const r of rows) {
      const key =
        groupBy === 'account'
          ? r.account
          : groupBy === 'sleeve'
            ? (r.sleeve ?? '–')
            : groupBy === 'asset_class'
              ? r.asset_class
              : ''
      out.set(key, [...(out.get(key) ?? []), r])
    }
    return [...out.entries()]
  }, [rows, groupBy])
  if (data.empty) return <p className="text-sm text-muted">{data.reason}</p>
  const numeric = (c: string) => c !== 'name' && c !== 'account'
  const cell = (r: (typeof rows)[number], c: string) => {
    switch (c) {
      case 'name':
        return (
          <Link to={`/holdings/${r.instrument_id}`} className="underline-offset-2 hover:underline">
            {r.name}
          </Link>
        )
      case 'account':
        return r.account
      case 'quantity':
        return qty(r.quantity)
      case 'close':
        return r.close === null ? '–' : eur(r.close)
      case 'value':
        return r.value === null ? '–' : eur(r.value)
      case 'weight':
        return r.weight === null ? '–' : pct(r.weight, 1)
      case 'unrealized':
        return <Delta value={r.unrealized} />
      case 'day':
        return <Delta value={r.day} />
      case 'income':
        return eur(r.income)
      default:
        return <Delta value={r.total_return} />
    }
  }
  return (
    <div className="h-full overflow-auto">
      <table className="w-full text-sm">
        <caption className="sr-only">{t('widgets.holdings_table')}</caption>
        <thead>
          <tr className="border-b border-border">
            {columns.map((c) => (
              <th
                key={c}
                scope="col"
                className={`px-2 py-1 font-medium ${numeric(c) ? 'text-right' : 'text-left'}`}
              >
                {t(`widgets.columns.${c}`)}
              </th>
            ))}
          </tr>
        </thead>
        {groups.map(([group, list]) => (
          <tbody key={group}>
            {groupBy !== 'none' && (
              <tr className="bg-border/30">
                <th
                  scope="rowgroup"
                  colSpan={columns.length}
                  className="px-2 py-1 text-left text-xs font-medium"
                >
                  {group}
                </th>
              </tr>
            )}
            {list.map((r) => (
              <tr key={`${r.instrument_id}-${r.account}`} className="border-b border-border">
                {columns.map((c) => (
                  <td
                    key={c}
                    className={`px-2 py-1 ${numeric(c) ? 'text-right tabular-nums' : ''}`}
                  >
                    {cell(r, c)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        ))}
      </table>
    </div>
  )
}
