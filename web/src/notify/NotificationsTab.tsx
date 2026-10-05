import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, errorMessage, unwrap } from '../api/client'
import { SectionForm, sectionKey } from '../components/SectionForm'
import { Alert, Button } from '../components/ui'
import { useDeliveries } from './api'

const ROUTES = ['critical', 'high', 'medium', 'low', 'info', 'digest'] as const
const CHANNELS = ['home_assistant', 'ntfy'] as const
const SECRETS = ['home_assistant_token', 'ntfy_token']
const FIELDS = [
  'channel',
  'home_assistant_url',
  'home_assistant_service',
  'home_assistant_token',
  'ntfy_url',
  'ntfy_topic',
  'ntfy_token',
  'app_url',
  'quiet_hours_start',
  'quiet_hours_end',
  'daily_push_cap',
  'push_privacy',
  'digest_daily',
  'digest_daily_time',
  'digest_weekly',
]

type Values = Record<string, unknown>
type Routing = Record<string, string[]>

/** Settings, Notifications: the channels, quiet hours, cap, privacy and digests; the routing
 * matrix (FR-NT-03); a test push per channel (FR-NT-02); and the delivery log (FR-NT-08). */
export function NotificationsTab() {
  const { t } = useTranslation()
  return (
    <div className="space-y-8">
      <SectionForm section="notifications" fields={FIELDS} />
      <RoutingMatrix />
      <section className="space-y-2">
        <h3 className="font-medium">{t('notifySettings.test.title')}</h3>
        <p className="text-sm text-muted">{t('notifySettings.test.intro')}</p>
        <div className="flex flex-wrap gap-4">
          {CHANNELS.map((c) => (
            <SendTest key={c} channel={c} />
          ))}
        </div>
      </section>
      <DeliveryLog />
    </div>
  )
}

function RoutingMatrix() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: sectionKey('notifications'),
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/settings/{section}', { params: { path: { section: 'notifications' } } }),
      ) as Promise<Values>,
  })
  const [draft, setDraft] = useState<Routing | null>(null)
  const routing: Routing = draft ?? (query.data?.routing as Routing | undefined) ?? {}
  const save = useMutation({
    mutationFn: () => {
      const body: Values = { ...(query.data ?? {}), routing }
      for (const key of SECRETS) body[key] = null // keep the saved tokens as they are
      return unwrap(
        api.PUT('/api/v1/settings/{section}', {
          params: { path: { section: 'notifications' } },
          body,
        }),
      )
    },
    onSuccess: async () => {
      setDraft(null)
      await queryClient.invalidateQueries({ queryKey: sectionKey('notifications') })
    },
  })
  if (!query.data) return null
  const toggle = (route: string, channel: string, on: boolean) => {
    const current = routing[route] ?? []
    setDraft({
      ...routing,
      [route]: on
        ? [...current.filter((c) => c !== channel), channel]
        : current.filter((c) => c !== channel),
    })
  }
  return (
    <section className="space-y-2">
      <h3 className="font-medium">{t('notifySettings.matrix.title')}</h3>
      <p className="text-sm text-muted">{t('notifySettings.matrix.intro')}</p>
      <div className="overflow-x-auto">
        <table className="text-sm">
          <caption className="sr-only">{t('notifySettings.matrix.title')}</caption>
          <thead>
            <tr className="border-b border-border text-left">
              <th scope="col" className="py-1 pr-4 font-medium">
                {t('notifySettings.matrix.severity')}
              </th>
              {CHANNELS.map((c) => (
                <th key={c} scope="col" className="px-3 py-1 text-center font-medium">
                  {t(`notifySettings.channels.${c}`)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ROUTES.map((route) => (
              <tr key={route} className="border-b border-border">
                <th scope="row" className="py-1 pr-4 text-left font-normal">
                  {t(`notifySettings.routes.${route}`)}
                </th>
                {CHANNELS.map((c) => (
                  <td key={c} className="px-3 py-1 text-center">
                    <input
                      type="checkbox"
                      className="size-4 accent-[var(--primary)]"
                      aria-label={t('notifySettings.matrix.cell', {
                        route: t(`notifySettings.routes.${route}`),
                        channel: t(`notifySettings.channels.${c}`),
                      })}
                      checked={(routing[route] ?? []).includes(c)}
                      onChange={(e) => toggle(route, c, e.target.checked)}
                    />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex items-center gap-2">
        <Button onClick={() => save.mutate()} disabled={draft === null || save.isPending}>
          {t('notifySettings.matrix.save')}
        </Button>
        {save.isSuccess && draft === null && (
          <span role="status" className="text-sm">
            {t('notifySettings.matrix.saved')}
          </span>
        )}
      </div>
      {save.isError && <Alert>{errorMessage(save.error)}</Alert>}
    </section>
  )
}

function SendTest({ channel }: { channel: 'home_assistant' | 'ntfy' }) {
  const { t } = useTranslation()
  const test = useMutation({
    mutationFn: () =>
      unwrap(api.POST('/api/v1/notifications/test/{channel}', { params: { path: { channel } } })),
  })
  const name = t(`notifySettings.channels.${channel}`)
  return (
    <div className="space-y-1">
      <Button variant="secondary" onClick={() => test.mutate()} disabled={test.isPending}>
        {t('notifySettings.test.send', { channel: name })}
      </Button>
      {test.data && (
        <p role="status" className={`text-sm ${test.data.ok ? '' : 'text-danger'}`}>
          {test.data.ok ? t('notifySettings.test.ok', { channel: name }) : test.data.error}
        </p>
      )}
      {test.isError && <Alert>{errorMessage(test.error)}</Alert>}
    </div>
  )
}

function DeliveryLog() {
  const { t } = useTranslation()
  const log = useDeliveries()
  const rows = log.data ?? []
  return (
    <section className="space-y-2">
      <h3 className="font-medium">{t('notifySettings.log.title')}</h3>
      {rows.length === 0 ? (
        <p className="text-sm text-muted">{t('notifySettings.log.empty')}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <caption className="sr-only">{t('notifySettings.log.title')}</caption>
            <thead>
              <tr className="border-b border-border text-left">
                {(['item', 'channel', 'status', 'attempts', 'when', 'error'] as const).map((c) => (
                  <th key={c} scope="col" className="py-1 pr-3 font-medium">
                    {t(`notifySettings.log.columns.${c}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((d) => (
                <tr key={d.id} className="border-b border-border">
                  <td className="py-1 pr-3">#{d.notification_id}</td>
                  <td className="py-1 pr-3">
                    {t(`notifySettings.channels.${d.channel}`, { defaultValue: d.channel })}
                  </td>
                  <td className="py-1 pr-3">
                    {t(`notifySettings.log.status.${d.status}`, { defaultValue: d.status })}
                  </td>
                  <td className="py-1 pr-3 tabular-nums">{d.attempts}</td>
                  <td className="py-1 pr-3">
                    {d.sent_at ? new Date(d.sent_at).toLocaleString() : '–'}
                  </td>
                  <td className="py-1 pr-3 text-danger">{d.last_error ?? ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
