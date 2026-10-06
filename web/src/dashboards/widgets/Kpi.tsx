import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { Delta } from '../../components/display'
import { toNumber } from '../../lib/format'
import { useFormat } from '../../lib/useFormat'
import { Sparkline } from '../charts/Bars'
import type { KpiData, WidgetProps } from '../types'
import { ReturnBreakdown } from './ReturnBreakdown'

/** Where a figure leads when clicked (FR-DB-06). */
export function kpiTarget(metric: string): string {
  if (['income', 'net_contributions', 'cash'].includes(metric)) return '/reports'
  if (['volatility', 'max_drawdown', 'current_drawdown', 'sharpe', 'beta'].includes(metric))
    return '/dashboards'
  return '/holdings'
}

/** One figure with its change and a sparkline: the figure is the chart. */
export function KpiWidget({ data, config }: WidgetProps<KpiData>) {
  const { t } = useTranslation()
  const { eur, num, pct } = useFormat()
  const [explaining, setExplaining] = useState(false)
  if (data.empty || data.value === null) {
    return <p className="text-sm text-muted">{data.reason ?? data.note ?? t('widgets.noFigure')}</p>
  }
  const value =
    data.kind === 'eur' ? eur(data.value) : data.kind === 'pct' ? pct(data.value) : num(data.value)
  const signed = ['day_change', 'total_return', 'period_return', 'largest_drift'].includes(
    data.metric,
  )
  return (
    <div className="flex h-full flex-col gap-1">
      <Link
        to={kpiTarget(data.metric)}
        className="flex min-h-0 flex-1 flex-col justify-between gap-1 no-underline"
      >
        <div>
          {/* the title says which figure this is; a title of the owner's own gets the name beside it */}
          {typeof config.title === 'string' && config.title.trim() !== '' && (
            <p className="text-sm text-muted">{t(`widgets.metrics.${data.metric}`)}</p>
          )}
          <p className="text-3xl font-semibold [font-variant-numeric:normal]">
            {signed ? (
              <Delta value={data.value} kind={data.kind === 'pct' ? 'pct' : 'eur'} />
            ) : (
              value
            )}
          </p>
          {data.label && <p className="text-xs text-muted">{data.label}</p>}
          {data.note && <p className="text-xs text-muted">{data.note}</p>}
          {data.change_ratio !== undefined && data.change_ratio !== null && (
            <p className="text-sm">
              <Delta value={data.change_ratio} kind="pct" />
            </p>
          )}
          {data.metric !== 'value' && data.change_eur && toNumber(data.change_eur) !== null && (
            <p className="text-xs text-muted">
              {t('widgets.resultInPeriod')}: <Delta value={data.change_eur} />
            </p>
          )}
        </div>
        <Sparkline
          values={data.sparkline.map((p) => Number(p.value))}
          label={t('widgets.sparkline')}
        />
      </Link>
      {data.breakdown && (
        <button
          type="button"
          onClick={() => setExplaining(true)}
          className="self-start text-xs underline underline-offset-2"
        >
          {t('breakdown.open')}
        </button>
      )}
      {explaining && <ReturnBreakdown data={data} onClose={() => setExplaining(false)} />}
    </div>
  )
}
