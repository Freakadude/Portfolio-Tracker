import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useFormat } from '../lib/useFormat'
import { api, errorMessage, unwrap } from '../api/client'
import { Alert } from '../components/ui'
import { Containers } from './Containers'

function size(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return '–'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`
}

/** Version and build, disk use, the agent's cost this month and recent failures (FR-SY-10). */
export function SystemInfo() {
  const { t } = useTranslation()
  const { num } = useFormat()
  const info = useQuery({
    queryKey: ['system', 'info'],
    queryFn: () => unwrap(api.GET('/api/v1/system/info')),
    refetchInterval: 30_000, // so the uptime moves
  })
  if (info.isError) return <Alert>{errorMessage(info.error)}</Alert>
  const d = info.data
  return (
    <section className="space-y-2" aria-labelledby="info-title">
      <h2 id="info-title" className="text-lg font-semibold">
        {t('systemInfo.title')}
      </h2>
      {d && <Containers web={d.web} worker={d.worker ?? null} />}
      {d && (
        <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Item label={t('systemInfo.version')}>
            {d.version}
            {d.build && <span className="ml-1 text-xs text-muted">({d.build.slice(0, 12)})</span>}
          </Item>
          <Item label={t('systemInfo.database')}>{size(d.disk.database_bytes)}</Item>
          <Item label={t('systemInfo.backups')}>
            {t('systemInfo.backupsValue', {
              count: d.disk.backups,
              size: size(d.disk.backups_bytes),
            })}
          </Item>
          <Item label={t('systemInfo.free')}>
            {size(d.disk.free_bytes)} / {size(d.disk.total_bytes)}
          </Item>
          <Item label={t('systemInfo.agent')}>
            {t('systemInfo.agentValue', {
              runs: d.agent.runs_this_month,
              cost: num(d.agent.cost_this_month_eur),
              budget: num(d.agent.budget_eur),
            })}
            {d.agent.note && <span className="block text-xs text-muted">{d.agent.note}</span>}
          </Item>
          {d.failing_news_sources.length > 0 && (
            <Item label={t('systemInfo.failingNews')}>
              <span className="font-semibold text-danger">{d.failing_news_sources.join(', ')}</span>
            </Item>
          )}
          <Item label={t('systemInfo.failed')}>
            <span className={d.failed_jobs_24h > 0 ? 'font-semibold text-danger' : ''}>
              {d.failed_jobs_24h}
            </span>
          </Item>
        </dl>
      )}
      <p className="max-w-2xl text-sm text-muted">
        {t('systemInfo.diagnosticsNote')}{' '}
        <a
          href="/api/v1/system/diagnostics"
          download
          className="font-medium text-primary underline underline-offset-2"
        >
          {t('systemInfo.diagnostics')}
        </a>
      </p>
    </section>
  )
}

function Item({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-border p-3">
      <dt className="text-sm text-muted">{label}</dt>
      <dd className="mt-1 font-medium tabular-nums">{children}</dd>
    </div>
  )
}
