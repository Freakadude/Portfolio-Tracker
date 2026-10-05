import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { toNumber } from '../../lib/format'
import { useFormat } from '../../lib/useFormat'
import { ChartFrame, DataTable } from '../charts/ChartFrame'
import { SERIES } from '../charts/palette'
import { TimeChart, type TimeSeries } from '../charts/TimeChart'
import type { MacroData, WidgetProps } from '../types'

const n = (v: string | null | undefined) => toNumber(v) ?? 0

/** One or two indicator series, and optionally a position rebased to 100, each in its own pane
 * on the same time axis: never two y-scales on one plot (FR-MD-08). */
export function MacroWidget({ data }: WidgetProps<MacroData>) {
  const { t } = useTranslation()
  const { num } = useFormat()
  const panes = useMemo(() => {
    const out: { key: string; label: string; unit: string; series: TimeSeries }[] = (
      data.panes ?? []
    ).map((p, i) => ({
      key: p.code,
      label: p.name,
      unit: p.unit,
      series: {
        key: p.code,
        label: p.name,
        color: SERIES[i % SERIES.length],
        points: p.points.map((x) => ({ time: x.date, value: n(x.value) })),
      },
    }))
    if (data.instrument) {
      out.push({
        key: `instrument:${data.instrument.id}`,
        label: `${data.instrument.name} (${t('widgets.rebasedShort')})`,
        unit: 'index',
        series: {
          key: 'instrument',
          label: data.instrument.name,
          color: SERIES[2],
          points: data.instrument.points.map((x) => ({ time: x.date, value: n(x.value) })),
        },
      })
    }
    return out
  }, [data.panes, data.instrument, t])
  if (data.empty) return <p className="text-sm text-muted">{data.reason}</p>
  const dates = [...new Set(panes.flatMap((p) => p.series.points.map((x) => x.time)))]
    .sort()
    .reverse()
  return (
    <ChartFrame
      chart={
        <div className="flex h-full flex-col gap-2">
          {panes.map((p) => (
            <div key={p.key} className="min-h-24 flex-1">
              <p className="text-xs font-medium">
                {p.label}
                {p.unit === 'percent' ? ' (%)' : ''}
              </p>
              <TimeChart series={[p.series]} label={p.label} format={(v) => num(v, 2)} />
            </div>
          ))}
          <Link to="/settings" className="text-xs text-muted underline">
            {t('widgets.macroSettings')}
          </Link>
        </div>
      }
      table={
        <DataTable
          caption={t('widgets.macro_overlay')}
          head={[t('charts.date'), ...panes.map((p) => p.label)]}
          rows={dates.map((d) => [
            d,
            ...panes.map((p) => {
              const hit = p.series.points.find((x) => x.time === d)
              return hit ? num(hit.value, 2) : '–'
            }),
          ])}
        />
      }
    />
  )
}
