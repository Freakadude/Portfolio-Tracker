import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api, errorMessage, unwrap } from '../api/client'
import { Badge } from '../components/display'
import { Alert } from '../components/ui'
import { useFormat } from '../lib/useFormat'

/** System: when the markets your holdings trade on are open, in your own time zone. Prices of a
 * holding only change while its market is open, which is why the delayed quotes pause outside
 * these hours. */
export function MarketsPanel() {
  const { t } = useTranslation()
  const { clock, dayClock, timezone } = useFormat()
  const markets = useQuery({
    queryKey: ['system', 'markets'],
    queryFn: () => unwrap(api.GET('/api/v1/system/markets')),
    refetchInterval: 60_000,
  })
  return (
    <section className="space-y-2" aria-labelledby="markets-title">
      <h2 id="markets-title" className="text-lg font-semibold">
        {t('system.markets.title')}
      </h2>
      <p className="text-sm text-muted">
        {t('system.markets.intro', { zone: timezone ?? t('system.markets.yourZone') })}
      </p>
      {markets.isError && <Alert>{errorMessage(markets.error)}</Alert>}
      {markets.data?.length === 0 && (
        <p className="text-sm text-muted">{t('system.markets.none')}</p>
      )}
      {!!markets.data?.length && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <caption className="sr-only">{t('system.markets.caption')}</caption>
            <thead>
              <tr className="border-b border-border text-left">
                {(['market', 'status', 'hours', 'holdings'] as const).map((c) => (
                  <th key={c} scope="col" className="py-2 pr-3 font-medium">
                    {t(`system.markets.columns.${c}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {markets.data.map((m) => (
                <tr key={m.mic} className="border-b border-border align-top">
                  <td className="py-2 pr-3">
                    <div className="font-medium">{m.name}</div>
                    <div className="text-xs text-muted">{m.mic}</div>
                  </td>
                  <td className="py-2 pr-3">
                    {m.open_now ? (
                      <>
                        <Badge tone="good">{t('system.markets.open')}</Badge>
                        <div className="text-xs text-muted">
                          {t('system.markets.closesAt', { time: clock(m.closes) })}
                        </div>
                      </>
                    ) : (
                      <>
                        <Badge>{t('system.markets.closed')}</Badge>
                        <div className="text-xs text-muted">
                          {m.next_open
                            ? t('system.markets.opensAt', { time: dayClock(m.next_open) })
                            : ''}
                        </div>
                      </>
                    )}
                  </td>
                  <td className="py-2 pr-3 whitespace-nowrap tabular-nums">
                    {m.opens && m.closes ? (
                      `${clock(m.opens)} – ${clock(m.closes)}`
                    ) : (
                      <span className="text-muted">{t('system.markets.noSession')}</span>
                    )}
                  </td>
                  <td className="py-2 pr-3">
                    {m.holdings.join(', ')}
                    {m.watching.length > 0 && (
                      <div className="text-xs text-muted">
                        {t('system.markets.watching', { names: m.watching.join(', ') })}
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
