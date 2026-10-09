import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import type { TFunction } from 'i18next'
import { errorMessage } from '../api/client'
import { Badge } from '../components/display'
import { Panel } from '../components/Panel'
import { Alert, Button, Field, Input, Select } from '../components/ui'
import { cn } from '../lib/cn'
import { stripeOf, toneOf } from '../lib/severity'
import { useInbox, useMarkRead, type Delivery, type InboxFilters, type Notification } from './api'

const SEVERITIES = ['critical', 'high', 'medium', 'low', 'info'] as const
const SOURCES = ['signal', 'alert', 'news', 'agent', 'digest', 'system'] as const
const STATUSES = ['all', 'unread', 'read'] as const
const SUMMARY_CHARS = 160

/** The first line of an item's text, cut short: what the item is about at a glance. The rest
 * of the text is the details. */
export function splitBody(body: string): { summary: string; details: string } {
  const text = body.trim()
  const newline = text.indexOf('\n')
  const first = (newline === -1 ? text : text.slice(0, newline)).trim()
  if (first.length <= SUMMARY_CHARS) {
    return { summary: first, details: newline === -1 ? '' : text.slice(newline + 1).trim() }
  }
  const cut = first.slice(0, SUMMARY_CHARS)
  const space = cut.lastIndexOf(' ')
  const summary = `${(space > 80 ? cut.slice(0, space) : cut).trimEnd()}…`
  return { summary, details: text }
}

/** What the main button of an item does, by where its link leads. */
export function openLabel(link: string, t: TFunction): string {
  if (link.startsWith('/holdings/')) return t('inbox.openPosition')
  if (link.startsWith('/news')) return t('inbox.openStory')
  if (link.startsWith('/strategies/review')) return t('inbox.openReview')
  if (link.startsWith('/insights')) return t('inbox.openAdvice')
  return t('inbox.open')
}

const relative = new Intl.RelativeTimeFormat('en', { numeric: 'auto' })

/** "5 minutes ago", "yesterday"; the exact time is the tooltip. */
export function ago(iso: string, now = Date.now()): string {
  const seconds = Math.round((new Date(iso).getTime() - now) / 1000)
  const steps: [Intl.RelativeTimeFormatUnit, number][] = [
    ['day', 86400],
    ['hour', 3600],
    ['minute', 60],
  ]
  for (const [unit, size] of steps) {
    if (Math.abs(seconds) >= size) return relative.format(Math.round(seconds / size), unit)
  }
  return relative.format(0, 'second')
}

/** Everything Folio told you, newest first, as cards: what it is (header), what it says
 * (summary), the rest (details) and what you can do about it (buttons) (FR-NT-01). The delivery
 * to each phone channel is part of the details. */
export function Inbox() {
  const { t } = useTranslation()
  const [filters, setFilters] = useState<InboxFilters>({ status: 'all' })
  const [chosen, setChosen] = useState<Set<number>>(new Set())
  const inbox = useInbox(filters)
  const mark = useMarkRead()
  const items = inbox.data?.items ?? []
  const unread = inbox.data?.unread ?? 0
  const set = (key: keyof InboxFilters, value: string) =>
    setFilters((f) => ({ ...f, [key]: value || undefined }))
  const toggle = (id: number, on: boolean) =>
    setChosen((c) => {
      const next = new Set(c)
      if (on) next.add(id)
      else next.delete(id)
      return next
    })
  const status = filters.status ?? 'all'

  return (
    <Panel
      id="insights-inbox"
      title={t('inbox.title')}
      count={unread}
      status={inbox.data ? t(unread > 0 ? 'inbox.unreadWord' : 'inbox.allRead') : undefined}
      actions={
        <Button
          variant="secondary"
          disabled={mark.isPending}
          onClick={() => mark.mutate({ all: true })}
        >
          {t('inbox.markAll')}
        </Button>
      }
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div role="group" aria-label={t('inbox.filter.status')} className="flex gap-1">
          {STATUSES.map((s) => (
            <button
              key={s}
              type="button"
              aria-pressed={status === s}
              onClick={() => set('status', s)}
              className={cn(
                'min-h-9 rounded-full border px-4 text-sm',
                status === s
                  ? 'border-primary bg-primary text-primary-foreground'
                  : 'border-border hover:bg-border/40',
              )}
            >
              {t(`inbox.status.${s}`)}
            </button>
          ))}
        </div>
        <Button
          variant="ghost"
          disabled={chosen.size === 0 || mark.isPending}
          onClick={() =>
            mark.mutate({ ids: [...chosen] }, { onSuccess: () => setChosen(new Set()) })
          }
        >
          {chosen.size === 0
            ? t('inbox.markChosenNone')
            : t('inbox.markChosen', { count: chosen.size })}
        </Button>
      </div>
      <details className="text-sm">
        <summary className="cursor-pointer select-none py-1 text-muted">
          {t('inbox.moreFilters')}
        </summary>
        <form
          className="mt-2 grid gap-2 sm:grid-cols-3"
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
      </details>
      {inbox.isError && <Alert>{errorMessage(inbox.error)}</Alert>}
      {mark.isError && <Alert>{errorMessage(mark.error)}</Alert>}
      {inbox.isSuccess && items.length === 0 ? (
        <p className="text-muted">{t('inbox.empty')}</p>
      ) : (
        <ul className="space-y-3" aria-label={t('inbox.title')}>
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
    </Panel>
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
  const { summary, details } = splitBody(item.body)
  const stripe = stripeOf(item.severity)
  const hasMore = details !== '' || item.deliveries.length > 0
  return (
    <li
      aria-label={item.title}
      className={cn(
        'rounded-lg border border-l-4 p-4 shadow-sm',
        stripe,
        unread ? 'border-border bg-primary/5' : 'border-border bg-card',
      )}
    >
      <div className="flex items-start gap-3">
        <input
          type="checkbox"
          className="mt-1 size-4 shrink-0 accent-[var(--primary)]"
          aria-label={t('inbox.choose', { title: item.title })}
          checked={chosen}
          onChange={(e) => onChoose(e.target.checked)}
        />
        <div className="min-w-0 flex-1 space-y-2">
          <header className="space-y-1">
            <h3
              className={cn(
                'text-base leading-snug',
                unread ? 'font-semibold' : 'font-medium text-foreground/80',
              )}
            >
              {unread && (
                <span
                  aria-hidden="true"
                  className="mr-2 inline-block size-2.5 rounded-full bg-primary align-middle"
                />
              )}
              {item.title}
              {unread && <span className="sr-only"> {t('inbox.isUnread')}</span>}
            </h3>
            <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
              <Badge tone={toneOf(item.severity)}>
                {t(`strategies.severity.${item.severity}`, { defaultValue: item.severity })}
              </Badge>
              <span>{t(`inbox.sources.${item.source}`, { defaultValue: item.source })}</span>
              {item.subject && (
                <span className="rounded-full border border-border px-2 py-0.5">
                  {item.subject}
                </span>
              )}
              <time dateTime={item.created_at} title={new Date(item.created_at).toLocaleString()}>
                {ago(item.created_at)}
              </time>
            </p>
          </header>
          {summary && <p className={cn('text-sm', !unread && 'text-muted')}>{summary}</p>}
          {hasMore && (
            <details className="text-sm">
              <summary className="cursor-pointer select-none text-muted">
                {t('inbox.showDetails')}
              </summary>
              <div className="mt-2 space-y-2 rounded-md bg-border/30 p-3">
                {details && <p className="whitespace-pre-line">{details}</p>}
                {item.deliveries.length > 0 && (
                  <p className="flex flex-col gap-0.5">
                    {item.deliveries.map((d) => (
                      <DeliveryNote key={d.id} delivery={d} />
                    ))}
                  </p>
                )}
              </div>
            </details>
          )}
          {(item.link || unread) && (
            <div className="flex flex-wrap items-center gap-2 pt-1">
              {item.link && (
                <Link
                  to={item.link}
                  onClick={() => unread && onRead()}
                  className="inline-flex min-h-10 items-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:opacity-90"
                >
                  {openLabel(item.link, t)}
                  <span className="sr-only">: {item.title}</span>
                </Link>
              )}
              {unread && (
                <Button
                  variant="secondary"
                  onClick={onRead}
                  aria-label={`${t('inbox.markRead')}: ${item.title}`}
                >
                  {t('inbox.markRead')}
                </Button>
              )}
            </div>
          )}
        </div>
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
