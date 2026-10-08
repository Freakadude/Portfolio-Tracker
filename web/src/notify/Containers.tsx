import type { TFunction } from 'i18next'
import { useTranslation } from 'react-i18next'
import type { components } from '../api/schema'
import { Alert } from '../components/ui'
import { useFormat } from '../lib/useFormat'

type Container = components['schemas']['ContainerOut']

const COMMITS = 'https://github.com/Freakadude/Portfolio-Tracker/commit/'
const SHA = /^[0-9a-f]{7,40}$/

/** "45 s", "12 min", "3 h 12 min" or "2 d 4 h": how long something has been running. */
export function duration(seconds: number, t: TFunction): string {
  if (seconds < 60) return t('systemInfo.duration.seconds', { n: seconds })
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return t('systemInfo.duration.minutes', { n: minutes })
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return t('systemInfo.duration.hours', { h: hours, m: minutes % 60 })
  return t('systemInfo.duration.days', { d: Math.floor(hours / 24), h: hours % 24 })
}

/** Which commit each container runs and for how long (FR-SY-10): the web container that serves
 * this page and the worker that does the scheduled work. */
export function Containers({ web, worker }: { web: Container; worker: Container | null }) {
  const { t } = useTranslation()
  const different = !!web.build && !!worker?.build && web.build !== worker.build
  return (
    <div className="space-y-2">
      <dl className="grid gap-3 sm:grid-cols-2">
        <Running label={t('systemInfo.web')} container={web} />
        <Running label={t('systemInfo.worker')} container={worker} isWorker />
      </dl>
      {different && <Alert>{t('systemInfo.differentBuilds')}</Alert>}
    </div>
  )
}

function Running({
  label,
  container,
  isWorker = false,
}: {
  label: string
  container: Container | null
  isWorker?: boolean
}) {
  const { t } = useTranslation()
  const { when } = useFormat()
  return (
    <div className="rounded-lg border border-border p-3" data-testid={isWorker ? 'worker' : 'web'}>
      <dt className="text-sm text-muted">{label}</dt>
      <dd className="mt-1 space-y-0.5">
        {container === null ? (
          <span className="text-sm text-muted">{t('systemInfo.noReport')}</span>
        ) : (
          <>
            <span className="block font-medium tabular-nums">
              <Commit build={container.build} />
            </span>
            <span className="block text-sm">
              {t('systemInfo.running', { time: duration(container.uptime_seconds, t) })}
              <span className="ml-1 text-xs text-muted">
                {t('systemInfo.since', { when: when(container.started_at) })}
              </span>
            </span>
            {isWorker && !container.alive && (
              <span className="block text-sm font-semibold text-danger">
                {t('systemInfo.notSeen', {
                  time: duration(container.seen_seconds_ago ?? 0, t),
                })}
              </span>
            )}
          </>
        )}
      </dd>
    </div>
  )
}

function Commit({ build }: { build: string | null | undefined }) {
  const { t } = useTranslation()
  if (!build || !SHA.test(build)) {
    return <span className="text-muted">{t('systemInfo.devBuild')}</span>
  }
  return (
    <a
      href={`${COMMITS}${build}`}
      target="_blank"
      rel="noreferrer"
      title={build}
      className="underline underline-offset-2"
    >
      {t('systemInfo.commit', { sha: build.slice(0, 7) })}
    </a>
  )
}
