import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router-dom'
import { errorMessage } from '../api/client'
import { Badge } from '../components/display'
import { Panel } from '../components/Panel'
import { Alert, Button, Input, Select } from '../components/ui'
import { cn } from '../lib/cn'
import { stripeOf, toneOf } from '../lib/severity'
import { useFormat } from '../lib/useFormat'
import {
  useAgentBudget,
  useDecide,
  useRecommendation,
  useRecommendations,
  useRunNow,
  type RecStatus,
  type Recommendation,
} from './api'
import { JobStatus } from '../system/JobStatus'

const STATUSES: RecStatus[] = ['open', 'accepted', 'rejected', 'snoozed', 'expired']
const TRADES = ['direct_contribution', 'trim', 'rebalance']

/** The agent's advice on Insights (FR-AG-05): what needs a decision, with its evidence and the
 * calculation behind it. Every item says it is AI-generated and not financial advice, and an item
 * that departs from your principles carries its own badge. */
export function Recommendations() {
  const { t } = useTranslation()
  const { num } = useFormat()
  const [status, setStatus] = useState<RecStatus>('open')
  const [params] = useSearchParams()
  const focus = Number(params.get('recommendation')) || null
  const list = useRecommendations(status)
  const budget = useAgentBudget()
  const run = useRunNow()
  const items = (list.data ?? [])
    .slice()
    .sort((a, b) => (a.id === focus ? -1 : b.id === focus ? 1 : 0))
  return (
    <Panel
      id="insights-advice"
      title={t('recs.title')}
      count={status === 'open' ? items.length : undefined}
      forceOpen={focus !== null}
      actions={
        <>
          <Select
            aria-label={t('recs.show')}
            value={status}
            onChange={(e) => setStatus(e.target.value as RecStatus)}
          >
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {t(`recs.status.${s}`)}
              </option>
            ))}
          </Select>
          <Button
            variant="secondary"
            onClick={() => run.mutate({ runType: 'daily_review' })}
            disabled={run.isPending || budget.data?.enabled === false}
          >
            {t('recs.runNow')}
          </Button>
        </>
      }
    >
      <p className="text-sm text-muted">{t('recs.label')}</p>
      {budget.data && (
        <p className="text-xs text-muted">
          {t('recs.budget', {
            spent: num(budget.data.spent_eur),
            budget: num(budget.data.budget_eur),
          })}
          {!budget.data.key_set && ` ${t('recs.noKey')}`}
          {budget.data.paused && ` ${t('recs.paused')}`}
        </p>
      )}
      <JobStatus jobs={['agent_run']} from={run} />
      {run.isError && <Alert>{errorMessage(run.error)}</Alert>}
      {list.isError && <Alert>{errorMessage(list.error)}</Alert>}
      {list.isSuccess && items.length === 0 && (
        <p className="text-muted">{t(`recs.empty.${status}`)}</p>
      )}
      <ul className="space-y-4">
        {items.map((r) => (
          <li key={r.id}>
            <RecCard rec={r} open={status === 'open'} highlighted={r.id === focus} />
          </li>
        ))}
      </ul>
    </Panel>
  )
}

function RecCard({
  rec,
  open,
  highlighted,
}: {
  rec: Recommendation
  open: boolean
  highlighted: boolean
}) {
  const { t } = useTranslation()
  const { eur, num, qty } = useFormat()
  const detail = useRecommendation(rec.id)
  const decide = useDecide()
  const [rejecting, setRejecting] = useState(false)
  const [reason, setReason] = useState('')
  const [days, setDays] = useState('3')
  const orders = detail.data?.orders ?? []
  const stale = detail.data?.plan_current === false
  const proposal = JSON.stringify(
    orders.map((o) => ({ instrument_id: o.instrument_id, side: o.side, quantity: o.quantity })),
  )
  const trade = TRADES.includes(rec.action_type)
  const orderLine = orders
    .map((o) => `${t(`recs.side.${o.side}`)} ${qty(o.quantity)} ${o.name}`)
    .join(', ')
  return (
    <article
      aria-labelledby={`rec-${rec.id}`}
      className={cn(
        'space-y-4 rounded-lg border border-l-4 bg-card p-5 shadow-sm',
        stripeOf(rec.severity),
        highlighted ? 'border-primary ring-2 ring-primary/40' : 'border-border',
      )}
    >
      <header className="space-y-2">
        <h3 id={`rec-${rec.id}`} className="text-lg font-semibold leading-snug">
          {rec.title}
        </h3>
        <p className="flex flex-wrap items-center gap-2 text-xs">
          <Badge tone={toneOf(rec.severity)}>{t(`recs.severity.${rec.severity}`)}</Badge>
          <Badge>{t(`recs.action.${rec.action_type}`)}</Badge>
          <Badge>{t('recs.ai')}</Badge>
          {rec.departs_from_principles && <Badge tone="warn">{t('recs.departs')}</Badge>}
        </p>
      </header>
      <div className="space-y-2">
        <p className="text-base">{rec.summary}</p>
        {orders.length > 0 && (
          <p className="text-sm font-medium">
            {t('recs.ordersLine', { count: orders.length, list: orderLine })}
          </p>
        )}
        {rec.departs_from_principles && (
          <p className="rounded-md border border-amber-600/60 bg-amber-500/10 p-3 text-sm">
            <strong>{t('recs.departsWhy')}</strong> {rec.departs_from_principles}
          </p>
        )}
      </div>
      {open && stale && <Alert>{t('recs.stale')}</Alert>}
      <details className="text-sm">
        <summary className="cursor-pointer select-none font-medium text-primary">
          {t('recs.details')}
        </summary>
        <div className="mt-3 space-y-4 rounded-md bg-border/30 p-4">
          <section className="space-y-1">
            <h4 className="font-medium">{t('recs.why')}</h4>
            <p className="text-muted">{rec.rationale}</p>
            <p className="text-xs text-muted">
              {t('recs.confidence', { level: t(`news.level.${rec.confidence}`) })}
              {' · '}
              {t('recs.expires', { date: new Date(rec.expires_at).toLocaleDateString() })}
            </p>
          </section>
          {orders.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <caption className="mb-1 text-left font-medium">{t('recs.orders')}</caption>
                <thead>
                  <tr className="border-b border-border text-left">
                    {(['side', 'name', 'quantity', 'price', 'amount'] as const).map((c) => (
                      <th key={c} scope="col" className="py-1 pr-3 font-medium">
                        {t(`recs.columns.${c}`)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {orders.map((o) => (
                    <tr key={`${o.side}-${o.instrument_id}`} className="border-b border-border">
                      <td className="py-1 pr-3">{t(`recs.side.${o.side}`)}</td>
                      <td className="py-1 pr-3">{o.name}</td>
                      <td className="py-1 pr-3 tabular-nums">{qty(o.quantity)}</td>
                      <td className="py-1 pr-3 tabular-nums">
                        {num(o.price)} {o.currency}
                      </td>
                      <td className="py-1 pr-3 tabular-nums">{eur(o.amount_eur)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <section className="space-y-1">
            <h4 className="font-medium">{t('recs.evidence')}</h4>
            <ul className="space-y-0.5">
              {rec.evidence.map((e) => (
                <li key={`${e.kind}-${e.ref}`}>
                  <span className="text-muted">{t(`recs.kind.${e.kind}`)}</span> {e.note}
                  {e.kind === 'web_source' && (
                    <>
                      {' '}
                      <a
                        href={e.ref}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="underline"
                      >
                        {e.ref}
                      </a>
                    </>
                  )}
                  {e.kind === 'news_cluster' && (
                    <>
                      {' '}
                      <Link to={`/news?cluster=${e.ref}`} className="underline">
                        {t('recs.openStory')}
                      </Link>
                    </>
                  )}
                </li>
              ))}
            </ul>
            {rec.sources.length > 0 && (
              <ul className="space-y-0.5">
                {rec.sources.map((src) => (
                  <li key={src}>
                    <a href={src} target="_blank" rel="noopener noreferrer" className="underline">
                      {src}
                    </a>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <p className="text-muted">{rec.what_would_change_this}</p>
        </div>
      </details>
      {!open && rec.user_note && (
        <p className="text-sm text-muted">{t('recs.yourReason', { note: rec.user_note })}</p>
      )}
      {open && (
        <div className="space-y-3 border-t border-border pt-4">
          <div className="flex flex-wrap items-center gap-2">
            <Button
              onClick={() => decide.mutate({ id: rec.id, action: 'accept' })}
              disabled={decide.isPending}
              aria-label={`${t('recs.accept')}: ${rec.title}`}
            >
              {t('recs.accept')}
            </Button>
            {trade && orders.length > 0 && (
              <Button
                variant="secondary"
                onClick={() => decide.mutate({ id: rec.id, action: 'accept', createDrafts: true })}
                disabled={decide.isPending || stale}
                aria-label={`${t('recs.acceptDrafts')}: ${rec.title}`}
              >
                {t('recs.acceptDrafts')}
              </Button>
            )}
            {orders.length > 0 && (
              <Link
                to={`/what-if?proposal=${encodeURIComponent(proposal)}`}
                className="inline-flex min-h-10 items-center rounded-md border border-border px-3 text-sm hover:bg-border/40"
              >
                {t('recs.whatIf')}
              </Link>
            )}
            <Button
              variant="secondary"
              onClick={() => setRejecting((v) => !v)}
              aria-label={`${t('recs.reject')}: ${rec.title}`}
            >
              {t('recs.reject')}
            </Button>
            {rec.status === 'new' && (
              <Button
                variant="ghost"
                onClick={() => decide.mutate({ id: rec.id, action: 'seen' })}
                disabled={decide.isPending}
                aria-label={`${t('recs.seen')}: ${rec.title}`}
              >
                {t('recs.seen')}
              </Button>
            )}
          </div>
          {rejecting && (
            <form
              className="flex flex-wrap items-end gap-2"
              onSubmit={(e) => {
                e.preventDefault()
                decide.mutate({ id: rec.id, action: 'reject', note: reason })
              }}
            >
              <label className="text-sm">
                {t('recs.reason')}
                <Input
                  value={reason}
                  maxLength={300}
                  onChange={(e) => setReason(e.target.value)}
                  className="mt-1 w-72"
                />
              </label>
              <Button type="submit" disabled={decide.isPending}>
                {t('recs.confirmReject')}
              </Button>
            </form>
          )}
          <div className="flex flex-wrap items-center gap-2 text-sm text-muted">
            <label>
              {t('recs.snoozeFor')}{' '}
              <Select
                value={days}
                onChange={(e) => setDays(e.target.value)}
                aria-label={t('recs.snoozeDays')}
                className="w-auto"
              >
                {[1, 3, 7, 14, 30].map((n) => (
                  <option key={n} value={n}>
                    {t('recs.days', { count: n })}
                  </option>
                ))}
              </Select>
            </label>
            <Button
              variant="ghost"
              onClick={() => decide.mutate({ id: rec.id, action: 'snooze', days: Number(days) })}
              disabled={decide.isPending}
              aria-label={`${t('recs.snooze')}: ${rec.title}`}
            >
              {t('recs.snooze')}
            </Button>
          </div>
        </div>
      )}
      {decide.isError && <Alert>{errorMessage(decide.error)}</Alert>}
      {decide.isSuccess && decide.data.drafts.length > 0 && (
        <p role="status" className="text-sm">
          {t('recs.draftsMade', { count: decide.data.drafts.length })}{' '}
          <Link to="/insights" className="underline">
            {t('recs.confirmDrafts')}
          </Link>
        </p>
      )}
    </article>
  )
}
