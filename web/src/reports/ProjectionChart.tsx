import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { ChartFrame, DataTable } from '../dashboards/charts/ChartFrame'
import { SERIES } from '../dashboards/charts/palette'
import { TimeChart, type TimeSeries } from '../dashboards/charts/TimeChart'
import { toNumber } from '../lib/format'
import { useFormat } from '../lib/useFormat'

export interface ProjectionRow {
  date: string
  invested: string
  p10: string
  median: string
  p90: string
}

export interface ProjectionAssumptions {
  start_value_eur: string
  monthly_contribution_eur: string
  annual_return_pct: string
  annual_volatility_pct: string
  years: number
  paths: number
}

const n = (v: string) => toNumber(v) ?? 0

/** The projection (FR-PF-12): the median with the 10th to 90th percentile band, against what
 * was simply paid in. The assumptions are written under the chart, and in its table view. */
export function ProjectionChart({
  rows,
  assumptions,
}: {
  rows: ProjectionRow[]
  assumptions: ProjectionAssumptions
}) {
  const { t } = useTranslation()
  const { eur, num } = useFormat()
  const format = useMemo(() => (v: number) => eur(v, 0), [eur])
  const series: TimeSeries[] = useMemo(
    () => [
      {
        key: 'p90',
        label: t('projection.p90'),
        color: SERIES[0],
        kind: 'band',
        points: rows.map((r) => ({ time: r.date, value: n(r.p90) })),
      },
      {
        key: 'p10',
        label: t('projection.p10'),
        color: SERIES[0],
        kind: 'mask',
        points: rows.map((r) => ({ time: r.date, value: n(r.p10) })),
      },
      {
        key: 'median',
        label: t('projection.median'),
        color: SERIES[0],
        points: rows.map((r) => ({ time: r.date, value: n(r.median) })),
      },
      {
        key: 'invested',
        label: t('projection.invested'),
        color: SERIES[1],
        points: rows.map((r) => ({ time: r.date, value: n(r.invested) })),
      },
    ],
    [rows, t],
  )
  const text = t('projection.assumptions', {
    start: eur(assumptions.start_value_eur, 0),
    contribution: eur(assumptions.monthly_contribution_eur, 0),
    ret: num(assumptions.annual_return_pct, 1),
    vol: num(assumptions.annual_volatility_pct, 1),
    years: assumptions.years,
    paths: assumptions.paths,
  })
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <ChartFrame
        chart={<TimeChart series={series} label={t('projection.chart')} format={format} />}
        table={
          <DataTable
            caption={t('projection.table')}
            head={[
              t('projection.columns.date'),
              t('projection.p10'),
              t('projection.median'),
              t('projection.p90'),
              t('projection.invested'),
            ]}
            rows={rows.map((r) => [r.date, eur(r.p10), eur(r.median), eur(r.p90), eur(r.invested)])}
          />
        }
      />
      <p className="text-xs text-muted">{text}</p>
    </div>
  )
}
