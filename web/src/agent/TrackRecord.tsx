import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../api/client'
import { Alert, Select } from '../components/ui'
import { useFormat } from '../lib/useFormat'
import { useTrackRecord } from './api'

type Horizon = 7 | 30 | 90

/** How the agent's past advice fared against later prices (FR-AG-06). */
export function TrackRecord() {
  const { t } = useTranslation()
  const { pct } = useFormat()
  const [horizon, setHorizon] = useState<Horizon>(30)
  const record = useTrackRecord(horizon)
  const data = record.data

  return (
    <section aria-labelledby="track-h" className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="track-h" className="text-lg font-semibold">
          {t('track.title')}
        </h2>
        <label className="flex items-center gap-2 text-sm">
          {t('track.horizons')}
          <Select
            value={horizon}
            onChange={(e) => setHorizon(Number(e.target.value) as Horizon)}
            aria-label={t('track.horizons')}
          >
            {([7, 30, 90] as const).map((d) => (
              <option key={d} value={d}>
                {t('track.horizon', { days: d })}
              </option>
            ))}
          </Select>
        </label>
      </div>
      {record.isError && <Alert>{errorMessage(record.error)}</Alert>}
      {data && data.total === 0 && <p className="text-muted">{t('track.empty')}</p>}
      {data && data.total > 0 && (
        <>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[32rem] text-sm">
              <caption className="sr-only">{t('track.caption')}</caption>
              <thead>
                <tr className="border-b border-border">
                  <th scope="col" className="px-3 py-2 text-left font-medium">
                    {t('track.action')}
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    {t('track.count')}
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    {t('track.measured')}
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    {t('track.hits')}
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    {t('track.avg')}
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.actions.map((a) => {
                  const h = a.by_horizon.find((x) => x.days === horizon)
                  return (
                    <tr key={a.action_type} className="border-b border-border">
                      <th scope="row" className="px-3 py-2 text-left font-normal">
                        {t(`track.types.${a.action_type}`, { defaultValue: a.action_type })}
                      </th>
                      <td className="px-3 py-2 text-right tabular-nums">{a.count}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{h?.measured ?? 0}</td>
                      <td className="px-3 py-2 text-right tabular-nums">
                        {!a.scored_type ? (
                          <span className="text-muted">{t('track.notScored')}</span>
                        ) : h && h.hit_rate !== null ? (
                          <>
                            {pct(h.hit_rate, 0)}{' '}
                            <span className="text-muted">
                              ({t('track.hitsOf', { hits: h.hits, scored: h.scored })})
                            </span>
                          </>
                        ) : (
                          '–'
                        )}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">
                        {h && h.avg_return !== null ? pct(h.avg_return) : '–'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <div className="overflow-x-auto">
            <h3 className="mb-1 text-sm font-medium">
              {t('track.byDecision', { days: data.decision_horizon })}
            </h3>
            <table className="w-full min-w-[32rem] text-sm">
              <caption className="sr-only">{t('track.decisionCaption')}</caption>
              <tbody>
                {data.decisions.map((d) => (
                  <tr key={d.decision} className="border-b border-border">
                    <th scope="row" className="px-3 py-2 text-left font-normal">
                      {t(`track.decision.${d.decision}`)}
                    </th>
                    <td className="px-3 py-2 text-right tabular-nums">{d.count}</td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {d.stats.hit_rate !== null
                        ? `${pct(d.stats.hit_rate, 0)} (${t('track.hitsOf', {
                            hits: d.stats.hits,
                            scored: d.stats.scored,
                          })})`
                        : '–'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-sm text-muted">{data.note}</p>
        </>
      )}
    </section>
  )
}
