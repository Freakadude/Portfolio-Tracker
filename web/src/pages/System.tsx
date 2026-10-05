import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, errorMessage, unwrap } from '../api/client'
import { useAudit, useJobs, useSystemUsage, type AuditFilters } from '../api/queries'
import { Badge } from '../components/display'
import { RunsPanel } from '../agent/RunsPanel'
import { SystemInfo } from '../notify/SystemInfo'
import { Alert, Button, Field, Input, Select } from '../components/ui'

export function System() {
  const { t } = useTranslation()
  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-semibold">{t('system.title')}</h1>
      <SystemInfo />
      <Usage />
      <Jobs />
      <RunsPanel />
      <AuditLog />
    </div>
  )
}

function Usage() {
  const { t } = useTranslation()
  const usage = useSystemUsage()
  return (
    <section className="space-y-2" aria-labelledby="usage-title">
      <h2 id="usage-title" className="text-lg font-semibold">
        {t('system.usage.title')}
      </h2>
      {usage.isError && <Alert>{errorMessage(usage.error)}</Alert>}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <caption className="sr-only">{t('system.usage.caption')}</caption>
          <thead>
            <tr className="border-b border-border text-left">
              <th scope="col" className="py-2 pr-3 font-medium">
                {t('system.usage.columns.provider')}
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-medium">
                {t('system.usage.columns.calls')}
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-medium">
                {t('system.usage.columns.budget')}
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-medium">
                {t('system.usage.columns.remaining')}
              </th>
              <th scope="col" className="py-2 font-medium">
                {t('system.usage.columns.state')}
              </th>
            </tr>
          </thead>
          <tbody>
            {usage.data?.map((u) => (
              <tr key={u.provider} className="border-b border-border">
                <th scope="row" className="py-2 pr-3 text-left font-normal capitalize">
                  {u.provider}
                </th>
                <td className="py-2 pr-3 text-right tabular-nums">{u.calls_today}</td>
                <td className="py-2 pr-3 text-right tabular-nums">
                  {u.daily_budget ?? t('system.usage.unlimited')}
                </td>
                <td className="py-2 pr-3 text-right tabular-nums">{u.remaining ?? '–'}</td>
                <td className="py-2">
                  <Badge tone={u.enabled ? 'good' : 'neutral'}>
                    {t(u.enabled ? 'system.usage.enabled' : 'system.usage.disabled')}
                  </Badge>{' '}
                  {u.has_key === false && <Badge tone="warn">{t('system.usage.noKey')}</Badge>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

const tone = (status: string) =>
  status === 'ok' || status === 'done'
    ? 'good'
    : status === 'failed' || status === 'error'
      ? 'bad'
      : 'neutral'

function Jobs() {
  const { t } = useTranslation()
  const jobs = useJobs()
  const refresh = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST('/api/v1/system/jobs/{job}/run', {
          params: { path: { job: 'refresh' } },
          body: { params: {} },
        }),
      ),
    onSuccess: () => jobs.refetch(),
  })
  const waiting =
    jobs.data?.requests.filter((r) => r.status === 'pending' || r.status === 'running') ?? []
  const status = (s: string) => t(`system.jobs.status.${s}`, { defaultValue: s })
  return (
    <section className="space-y-3" aria-labelledby="jobs-title">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="jobs-title" className="text-lg font-semibold">
          {t('system.jobs.title')}
        </h2>
        <Button onClick={() => refresh.mutate()} disabled={refresh.isPending}>
          {t('system.jobs.refresh')}
        </Button>
      </div>
      {refresh.isSuccess && <p role="status">{t('system.jobs.queued')}</p>}
      {refresh.isError && <Alert>{errorMessage(refresh.error)}</Alert>}
      {jobs.isError && <Alert>{errorMessage(jobs.error)}</Alert>}

      <h3 className="font-medium">{t('system.jobs.requests')}</h3>
      {waiting.length === 0 ? (
        <p className="text-muted">{t('system.jobs.noRequests')}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <caption className="sr-only">{t('system.jobs.requestsCaption')}</caption>
            <thead>
              <tr className="border-b border-border text-left">
                <th scope="col" className="py-1 pr-3 font-medium">
                  {t('system.jobs.columns.job')}
                </th>
                <th scope="col" className="py-1 pr-3 font-medium">
                  {t('system.jobs.columns.created')}
                </th>
                <th scope="col" className="py-1 font-medium">
                  {t('system.jobs.columns.status')}
                </th>
              </tr>
            </thead>
            <tbody>
              {waiting.map((r) => (
                <tr key={r.id} className="border-b border-border">
                  <td className="py-1 pr-3">{r.job}</td>
                  <td className="py-1 pr-3 whitespace-nowrap">
                    {r.created_at.slice(0, 19).replace('T', ' ')}
                  </td>
                  <td className="py-1">{status(r.status)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h3 className="font-medium">{t('system.jobs.runs')}</h3>
      {jobs.isSuccess && jobs.data.runs.length === 0 ? (
        <p className="text-muted">{t('system.jobs.none')}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <caption className="sr-only">{t('system.jobs.runsCaption')}</caption>
            <thead>
              <tr className="border-b border-border text-left">
                {(['job', 'started', 'duration', 'status', 'log'] as const).map((c) => (
                  <th key={c} scope="col" className="py-1 pr-3 font-medium">
                    {t(`system.jobs.columns.${c}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {jobs.data?.runs.map((r) => (
                <tr key={r.id} className="border-b border-border align-top">
                  <td className="py-1 pr-3">{r.job}</td>
                  <td className="py-1 pr-3 whitespace-nowrap">
                    {r.started_at.slice(0, 19).replace('T', ' ')}
                  </td>
                  <td className="py-1 pr-3 tabular-nums">
                    {r.duration_seconds === null
                      ? '–'
                      : t('system.jobs.seconds', { count: Math.round(r.duration_seconds) })}
                  </td>
                  <td className="py-1 pr-3">
                    <Badge tone={tone(r.status)}>{status(r.status)}</Badge>
                  </td>
                  <td className="py-1 text-muted">{r.log ?? ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

const ENTITIES = [
  'account',
  'corporate_action',
  'import_batch',
  'instrument',
  'price_bar',
  'setting',
  'transaction',
  'user',
]

function AuditLog() {
  const { t } = useTranslation()
  const [filters, setFilters] = useState<AuditFilters>({})
  const audit = useAudit(filters)
  const rows = audit.data?.pages.flatMap((p) => p.items) ?? []
  const set = (key: keyof AuditFilters, value: string) =>
    setFilters((f) => ({ ...f, [key]: value || undefined }))
  return (
    <section className="space-y-2" aria-labelledby="audit-title">
      <h2 id="audit-title" className="text-lg font-semibold">
        {t('system.audit.title')}
      </h2>
      <div className="grid gap-3 sm:grid-cols-4">
        <Field label={t('system.audit.filters.entity')}>
          {(p) => (
            <Select
              value={filters.entity ?? ''}
              onChange={(e) => set('entity', e.target.value)}
              {...p}
            >
              <option value="">{t('system.audit.filters.all')}</option>
              {ENTITIES.map((x) => (
                <option key={x} value={x}>
                  {x}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label={t('system.audit.filters.actor')}>
          {(p) => (
            <Input
              value={filters.actor ?? ''}
              onChange={(e) => set('actor', e.target.value)}
              {...p}
            />
          )}
        </Field>
        <Field label={t('system.audit.filters.from')}>
          {(p) => (
            <Input
              type="date"
              value={filters.from ?? ''}
              onChange={(e) => set('from', e.target.value)}
              {...p}
            />
          )}
        </Field>
        <Field label={t('system.audit.filters.to')}>
          {(p) => (
            <Input
              type="date"
              value={filters.to ?? ''}
              onChange={(e) => set('to', e.target.value)}
              {...p}
            />
          )}
        </Field>
      </div>
      {audit.isError && <Alert>{errorMessage(audit.error)}</Alert>}
      {audit.isSuccess && rows.length === 0 ? (
        <p className="text-muted">{t('system.audit.empty')}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <caption className="sr-only">{t('system.audit.caption')}</caption>
            <thead>
              <tr className="border-b border-border text-left">
                {(['when', 'who', 'action', 'record', 'changes'] as const).map((c) => (
                  <th key={c} scope="col" className="py-1 pr-3 font-medium">
                    {t(`system.audit.columns.${c}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-b border-border align-top">
                  <td className="py-1 pr-3 whitespace-nowrap">
                    {r.ts.slice(0, 19).replace('T', ' ')}
                  </td>
                  <td className="py-1 pr-3">{r.actor}</td>
                  <td className="py-1 pr-3">{r.action}</td>
                  <td className="py-1 pr-3">
                    {r.entity}
                    {r.entity_id ? ` #${r.entity_id}` : ''}
                  </td>
                  <td className="py-1">
                    <Diff diff={r.diff} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {audit.hasNextPage && (
        <Button
          variant="secondary"
          onClick={() => void audit.fetchNextPage()}
          disabled={audit.isFetchingNextPage}
        >
          {t('system.audit.more')}
        </Button>
      )}
    </section>
  )
}

/** old and new values side by side, so an edit can be understood without reading JSON. */
function Diff({ diff }: { diff: Record<string, unknown> | null }) {
  const { t } = useTranslation()
  if (!diff) return null
  return (
    <ul className="space-y-0.5">
      {Object.entries(diff).map(([key, value]) => {
        const change = value as { old?: unknown; new?: unknown } | null
        const isChange =
          change !== null && typeof change === 'object' && ('old' in change || 'new' in change)
        return (
          <li key={key}>
            <span className="font-medium">{key}</span>:{' '}
            {isChange ? (
              <>
                <span className="text-muted">{t('system.audit.before')}</span>{' '}
                {String(change.old ?? '–')}{' '}
                <span className="text-muted">{t('system.audit.after')}</span>{' '}
                {String(change.new ?? '–')}
              </>
            ) : (
              String(typeof value === 'object' ? JSON.stringify(value) : value)
            )}
          </li>
        )
      })}
    </ul>
  )
}
