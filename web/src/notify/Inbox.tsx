import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { errorMessage } from '../api/client'
import { Badge } from '../components/display'
import { Alert, Button, Field, Input, Select } from '../components/ui'
import { useInbox, useMarkRead, type Delivery, type InboxFilters, type Notification } from './api'

const SEVERITIES = ['critical', 'high', 'medium', 'low', 'info'] as const
const SOURCES = ['signal', 'alert', 'digest', 'system'] as const
const TONE = {
  critical: 'bad',
  high: 'bad',
  medium: 'warn',
  low: 'neutral',
  info: 'neutral',
} as const

/** Everything Folio told you, newest first, with filters, bulk mark-as-read and links to what
 * each item is about (FR-NT-01). The delivery to each phone channel is shown per item. */
export function Inbox() {
  const { t } = useTranslation()
  const [filters, setFilters] = useState<InboxFilters>({ status: 'all' })
  const [chosen, setChosen] = useState<Set<number>>(new Set())
  const inbox = useInbox(filters)
  const mark = useMarkRead()
  const items = inbox.data?.items ?? []
  const set = (key: keyof InboxFilters, value: string) =>
    setFilters((f) => ({ ...f, [key]: value || undefined }))
  const toggle = (id: number, on: boolean) =>
    setChosen((c) => {
      const next = new Set(c)
      if (on) next.add(id)
      else next.delete(id)
      return next
    })

  return (
    <section className="space-y-3" aria-labelledby="inbox-title">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="inbox-title" className="text-lg font-semibold">
          {t('inbox.title')}
          {inbox.data && inbox.data.unread > 0 && (
            <span className="ml-2 text-sm font-normal text-muted">
              {t('inbox.unread', { count: inbox.data.unread })}
            </span>
          )}
        </h2>
        <div className="flex flex-wrap gap-2">
          <Button
            variant="secondary"
            disabled={chosen.size === 0 || mark.isPending}
            onClick={() =>
              mark.mutate({ ids: [...chosen] }, { onSuccess: () => setChosen(new Set()) })
            }
          >
            {chosen.size === 0
              ? t('inbox.markChosenNone')
              : t('inbox.markChosen', { count: chosen.size })}
          </Button>
          <Button
            variant="ghost"
            disabled={mark.isPending}
            onClick={() => mark.mutate({ all: true })}
          >
            {t('inbox.markAll')}
          </Button>
        </div>
      </div>
      <form
        className="grid gap-2 sm:grid-cols-4"
        aria-label={t('inbox.filters')}
        onSubmit={(e) => e.preventDefault()}
      >
        <Field label={t('inbox.filter.severity')}>
          {(p) => (
            <Select
              value={filters.severity ?? ''}
              onChange={(e) => set('severity', e.target.value)}
              {...p}
            >
              <option value="">{t('inbox.filter.any')}</option>
              {SEVERITIES.map((s) => (
                <option key={s} value={s}>
                  {t(`strategies.severity.${s}`)}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label={t('inbox.filter.type')}>
          {(p) => (
            <Select
              value={filters.source ?? ''}
              onChange={(e) => set('source', e.target.value)}
              {...p}
            >
              <option value="">{t('inbox.filter.any')}</option>
              {SOURCES.map((s) => (
                <option key={s} value={s}>
                  {t(`inbox.sources.${s}`)}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label={t('inbox.filter.status')}>
          {(p) => (
            <Select
              value={filters.status ?? 'all'}
              onChange={(e) => set('status', e.target.value)}
              {...p}
            >
              {(['all', 'unread', 'read'] as const).map((s) => (
                <option key={s} value={s}>
                  {t(`inbox.status.${s}`)}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label={t('inbox.filter.subject')}>
          {(p) => (
            <Input
              value={filters.subject ?? ''}
              onChange={(e) => set('subject', e.target.value)}
              {...p}
            />
          )}
        </Field>
      </form>
      {inbox.isError && <Alert>{errorMessage(inbox.error)}</Alert>}
      {mark.isError && <Alert>{errorMessage(mark.error)}</Alert>}
      {inbox.isSuccess && items.length === 0 ? (
        <p className="text-muted">{t('inbox.empty')}</p>
      ) : (
        <ul className="space-y-2" aria-label={t('inbox.title')}>
          {items.map((n) => (
            <Item
              key={n.id}
              item={n}
              chosen={chosen.has(n.id)}
              onChoose={(on) => toggle(n.id, on)}
              onRead={() => mark.mutate({ ids: [n.id] })}
            />
          ))}
        </ul>
      )}
    </section>
  )
}

function Item({
  item,
  chosen,
  onChoose,
  onRead,
}: {
  item: Notification
  chosen: boolean
  onChoose: (on: boolean) => void
  onRead: () => void
}) {
  const { t } = useTranslation()
  const unread = item.read_at === null
  return (
    <li
      aria-label={item.title}
      className={`space-y-1 rounded-md border p-3 text-sm ${unread ? 'border-primary/60' : 'border-border'}`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="checkbox"
          className="size-4 accent-[var(--primary)]"
          aria-label={t('inbox.choose', { title: item.title })}
          checked={chosen}
          onChange={(e) => onChoose(e.target.checked)}
        />
        <Badge tone={TONE[item.severity as keyof typeof TONE] ?? 'neutral'}>
          {t(`strategies.severity.${item.severity}`, { defaultValue: item.severity })}
        </Badge>
        <span className="text-xs text-muted">
          {t(`inbox.sources.${item.source}`, { defaultValue: item.source })}
        </span>
        <span className={unread ? 'font-semibold' : 'font-medium'}>{item.title}</span>
        {unread && <span className="sr-only">{t('inbox.isUnread')}</span>}
        <span className="ml-auto text-xs text-muted">
          {new Date(item.created_at).toLocaleString()}
        </span>
      </div>
      <p className="whitespace-pre-line text-muted">{item.body}</p>
      <div className="flex flex-wrap items-center gap-3">
        {item.link && (
          <Link to={item.link} className="underline" onClick={() => unread && onRead()}>
            {t('inbox.open')}
          </Link>
        )}
        {unread && (
          <Button variant="ghost" className="min-h-8 px-2" onClick={onRead}>
            {t('inbox.markRead')}
          </Button>
        )}
        {item.deliveries.map((d) => (
          <DeliveryNote key={d.id} delivery={d} />
        ))}
      </div>
    </li>
  )
}

function DeliveryNote({ delivery }: { delivery: Delivery }) {
  const { t } = useTranslation()
  const channel = t(`notifySettings.channels.${delivery.channel}`, {
    defaultValue: delivery.channel,
  })
  const when = delivery.sent_at
    ? new Date(delivery.sent_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : ''
  const next = delivery.next_attempt_at
    ? new Date(delivery.next_attempt_at).toLocaleString([], {
        dateStyle: 'short',
        timeStyle: 'short',
      })
    : ''
  return (
    <span className={`text-xs ${delivery.status === 'failed' ? 'text-danger' : 'text-muted'}`}>
      {t(`inbox.delivery.${delivery.status}`, {
        channel,
        when,
        next,
        error: delivery.last_error ?? '',
      })}
    </span>
  )
}
