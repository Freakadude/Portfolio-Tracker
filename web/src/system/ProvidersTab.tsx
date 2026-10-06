import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, errorMessage, unwrap } from '../api/client'
import { useSystemUsage } from '../api/queries'
import { SectionForm, sectionKey } from '../components/SectionForm'
import { Badge } from '../components/display'
import { Alert, Checkbox } from '../components/ui'

type Config = { enabled: boolean; priority: number; daily_call_budget: number }

const KEYED = ['eodhd', 'twelvedata', 'fred']

/** Settings, Providers: every data source with what it is for, whether it has the key it
 * needs, how many calls it has used today, and a switch to turn it on or off; below that the
 * keys, and the priorities and call limits for those who want them. */
export function ProvidersTab() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const usage = useSystemUsage()
  // what the switch shows while the change is being saved
  const [shown, setShown] = useState<Record<string, boolean>>({})
  const settings = useQuery({
    queryKey: sectionKey('providers'),
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/settings/{section}', { params: { path: { section: 'providers' } } }),
      ) as Promise<{ providers: Record<string, Config> }>,
  })
  const toggle = useMutation({
    mutationFn: ({ name, enabled }: { name: string; enabled: boolean }) => {
      const current = settings.data?.providers ?? {}
      const next = { ...current, [name]: { ...current[name], enabled } }
      return unwrap(
        api.PUT('/api/v1/settings/{section}', {
          params: { path: { section: 'providers' } },
          body: { providers: next },
        }),
      )
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: sectionKey('providers') })
      await queryClient.invalidateQueries({ queryKey: ['system', 'usage'] })
    },
    onSettled: (_data, _error, { name }) =>
      setShown((prev) => Object.fromEntries(Object.entries(prev).filter(([k]) => k !== name))),
  })
  const rows = usage.data ?? []
  return (
    <div className="space-y-6">
      <p className="text-sm text-muted">{t('providers.intro')}</p>
      {usage.isError && <Alert>{errorMessage(usage.error)}</Alert>}
      {toggle.isError && <Alert>{errorMessage(toggle.error)}</Alert>}
      <ul className="space-y-2">
        {rows.map((u) => (
          <li
            key={u.provider}
            className="flex flex-wrap items-start justify-between gap-3 rounded-md border border-border p-3"
          >
            <div className="min-w-0 flex-1 space-y-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">
                  {t(`providers.names.${u.provider}`, { defaultValue: u.provider })}
                </span>
                {u.enabled && u.has_key === false && (
                  <Badge tone="warn">{t('providers.noKey')}</Badge>
                )}
                {!u.enabled && <Badge>{t('providers.off')}</Badge>}
              </div>
              <p className="text-sm text-muted">
                {t(`providers.what.${u.provider}`, { defaultValue: '' })}
              </p>
              <p className="text-xs text-muted">
                {u.daily_budget === null
                  ? t('providers.callsToday', { calls: u.calls_today })
                  : t('providers.callsTodayOf', { calls: u.calls_today, budget: u.daily_budget })}
              </p>
            </div>
            <Checkbox
              label={t('providers.on', {
                name: t(`providers.names.${u.provider}`, { defaultValue: u.provider }),
              })}
              checked={shown[u.provider] ?? u.enabled}
              disabled={toggle.isPending || settings.isPending}
              onChange={(e) => {
                setShown((prev) => ({ ...prev, [u.provider]: e.target.checked }))
                toggle.mutate({ name: u.provider, enabled: e.target.checked })
              }}
            />
          </li>
        ))}
      </ul>
      <section className="space-y-2">
        <h2 className="text-lg font-semibold">{t('providers.keys')}</h2>
        <p className="text-sm text-muted">{t('providers.keysHint', { names: KEYED.join(', ') })}</p>
        <SectionForm
          section="providers"
          fields={['eodhd_api_key', 'twelvedata_api_key', 'openfigi_api_key', 'fred_api_key']}
        />
      </section>
      <details className="rounded-md border border-border p-3">
        <summary className="cursor-pointer text-sm font-medium">{t('providers.advanced')}</summary>
        <p className="my-2 text-sm text-muted">{t('providers.advancedHint')}</p>
        <SectionForm section="providers" fields={['providers']} />
      </details>
    </div>
  )
}
