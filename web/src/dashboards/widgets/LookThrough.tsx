import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { useFormat } from '../../lib/useFormat'
import { ChartFrame, DataTable } from '../charts/ChartFrame'
import type { LookThroughData, WidgetProps } from '../types'
import { Where } from './Where'

/** The largest underlying exposures across direct holdings and ETFs (FR-PF-05): one bar each,
 * the table view adds where each one sits. A click opens the position that holds it. */
export function LookThroughWidget({ data }: WidgetProps<LookThroughData>) {
  const { t } = useTranslation()
  const { eur, pct } = useFormat()
  const navigate = useNavigate()
  if (data.empty) return <p className="text-sm text-muted">{data.reason}</p>
  const slices = data.slices ?? []
  const widest = Math.max(...slices.map((s) => Number(s.weight)), 0.0001)
  const dimension = data.dimension ?? 'company'
  return (
    <div className="flex h-full flex-col gap-2">
      <ChartFrame
        chart={
          <ol aria-label={t('widgets.look_through')} className="space-y-1.5">
            {slices.map((s) => {
              const first = s.parts[0]
              const open = () => first && navigate(`/holdings/${first.instrument_id}`)
              return (
                <li key={s.key}>
                  <button
                    type="button"
                    onClick={open}
                    disabled={!first || s.other}
                    className="block w-full text-left"
                    aria-label={t('lookThrough.openPosition', {
                      name: s.key,
                      weight: pct(s.weight, 1),
                    })}
                  >
                    <span className="flex justify-between gap-2 text-sm">
                      <span className="truncate">{s.key}</span>
                      <span className="tabular-nums">{pct(s.weight, 1)}</span>
                    </span>
                    <span className="mt-0.5 block h-2 rounded bg-border/50">
                      <span
                        className="block h-2 rounded"
                        style={{
                          width: `${(Number(s.weight) / widest) * 100}%`,
                          background: s.other ? 'var(--muted)' : 'var(--series-1, #2a6fdb)',
                        }}
                      />
                    </span>
                  </button>
                </li>
              )
            })}
          </ol>
        }
        table={
          <DataTable
            caption={t('widgets.look_through')}
            head={[
              t(`lookThrough.dimension.${dimension}`),
              t('widgets.value'),
              t('widgets.weight'),
              t('lookThrough.where'),
            ]}
            rows={slices.map((s) => [
              s.key,
              eur(s.value_eur, 0),
              pct(s.weight, 1),
              <Where key="w" parts={s.parts} />,
            ])}
          />
        }
      />
      {Number(data.rest_weight ?? 0) > 0 && (
        <p className="text-xs text-muted">
          {t('lookThrough.rest', { weight: pct(data.rest_weight ?? '0', 1) })}
        </p>
      )}
      <p className="text-xs text-muted">
        {(data.opened ?? []).length === 0
          ? t('lookThrough.openedNone')
          : t('lookThrough.opened', {
              names: (data.opened ?? []).map((o) => `${o.name} (${o.holdings_as_of})`).join(', '),
            })}
      </p>
      {(data.unopened ?? []).length > 0 && (
        <p className="text-xs text-muted">
          {t('lookThrough.unopened', { names: (data.unopened ?? []).join(', ') })}
        </p>
      )}
    </div>
  )
}
