import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { api, unwrap } from '../api/client'
import { useFormat } from '../lib/useFormat'

type Request = {
  id: number
  job: string
  status: string
  created_at: string
  finished_at: string | null
  error: string | null
}
type Run = { id: number; job: string; status: string; started_at: string; log: string | null }

const GRACE_MS = 60_000 // the browser's and the server's clocks may differ a little
const GIVE_UP_MS = 5 * 60_000

type Phase = 'asking' | 'waiting' | 'running' | 'done' | 'failed'

function phaseOf(requests: Request[], jobs: string[], since: number) {
  const mine = requests
    .filter(
      (r) =>
        jobs.includes(r.job) &&
        (r.status === 'pending' ||
          r.status === 'running' ||
          Date.parse(r.created_at) >= since - GRACE_MS),
    )
    .sort((a, b) => b.id - a.id)
  // anything still going counts first, then the newest that finished
  const live = mine.find((r) => r.status === 'pending' || r.status === 'running')
  const request = live ?? mine[0]
  const phase: Phase = !request
    ? 'asking'
    : request.status === 'pending'
      ? 'waiting'
      : request.status === 'running'
        ? 'running'
        : request.status === 'failed'
          ? 'failed'
          : 'done'
  return { phase, request }
}

/** What happened to the background work a button asked for, on the page of the button: asked,
 * waiting for the worker, working, then done (with the job's last log line) or failed (with the
 * reason). It looks again every second or two until the work is over. `from` is the button's mutation (its
 * submission time is when the button was pressed). `onDone` runs once when the work has finished. */
export function JobStatus({
  jobs,
  from,
  onDone,
}: {
  jobs: string[]
  /** The mutation behind the button: nothing is shown until it has succeeded. */
  from: { isSuccess: boolean; submittedAt: number }
  onDone?: () => void
}) {
  const since = from.isSuccess ? from.submittedAt : null
  const { t } = useTranslation()
  const { clock } = useFormat()
  const finished = useRef<number | null>(null)
  const watch = useQuery({
    queryKey: ['job-watch', jobs.join(','), since],
    enabled: !!since,
    queryFn: () => unwrap(api.GET('/api/v1/system/jobs', { params: { query: { limit: 30 } } })),
    refetchInterval: (query) => {
      const data = query.state.data
      if (!since || Date.now() - since > GIVE_UP_MS) return false
      if (!data) return 1000
      const { phase } = phaseOf(data.requests, jobs, since)
      return phase === 'done' || phase === 'failed' ? false : 1500
    },
  })
  const data = watch.data
  const { phase, request } =
    since && data
      ? phaseOf(data.requests, jobs, since)
      : { phase: 'asking' as Phase, request: undefined }
  const over = phase === 'done' || phase === 'failed'

  useEffect(() => {
    if (over && since && finished.current !== since) {
      finished.current = since
      onDone?.()
    }
  }, [over, since, onDone])

  if (!since) return null
  const lastRun: Run | undefined = data?.runs
    .filter((r) => jobs.includes(r.job) && Date.parse(r.started_at) >= since - GRACE_MS)
    .sort((a, b) => b.id - a.id)[0]
  const lastLine = lastRun?.log
    ?.split('\n')
    .map((l) => l.trim())
    .filter(Boolean)
    .pop()
  const slow = phase === 'waiting' && Date.now() - since > 30_000

  if (phase === 'failed') {
    return (
      <p role="alert" className="rounded-md border border-danger/50 px-3 py-2 text-sm text-danger">
        {t('jobStatus.failed', { reason: request?.error ?? t('jobStatus.noReason') })}
      </p>
    )
  }
  return (
    <div role="status" className="space-y-1 text-sm">
      <p>
        {phase === 'asking' && t('jobStatus.asking')}
        {phase === 'waiting' && t('jobStatus.waiting')}
        {phase === 'running' && t('jobStatus.running')}
        {phase === 'done' &&
          t('jobStatus.done', { time: clock(request?.finished_at ?? new Date().toISOString()) })}
      </p>
      {!over && (
        <div
          aria-hidden="true"
          className="h-1 w-48 overflow-hidden rounded bg-border"
          data-testid="job-progress"
        >
          <div className="h-full w-1/3 bg-primary motion-safe:animate-pulse" />
        </div>
      )}
      {phase === 'done' && lastLine && <p className="text-xs text-muted">{lastLine}</p>}
      {slow && <p className="text-xs text-muted">{t('jobStatus.slow')}</p>}
    </div>
  )
}
