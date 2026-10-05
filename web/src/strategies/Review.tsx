import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router-dom'
import { ApiProblem, api, errorMessage, unwrap } from '../api/client'
import { Alert, Button, Select } from '../components/ui'
import { useFormat } from '../lib/useFormat'

/** The last eight quarters, newest first, for the picker. */
function quarters(now = new Date()): string[] {
  let year = now.getFullYear()
  let q = Math.floor(now.getMonth() / 3) + 1
  const out: string[] = []
  for (let i = 0; i < 8; i++) {
    out.push(`${year}Q${q}`)
    q -= 1
    if (q === 0) {
      q = 4
      year -= 1
    }
  }
  return out
}

function lastCompleted(): string {
  return quarters()[1]
}

/** The summary of a quarter of the active strategy (FR-ST-08), made by code. */
export function StrategyReview() {
  const { t } = useTranslation()
  const { num } = useFormat()
  const [params, setParams] = useSearchParams()
  const quarter = params.get('quarter') ?? lastCompleted()
  const queryClient = useQueryClient()
  const review = useQuery({
    queryKey: ['strategy-review', quarter],
    queryFn: () => unwrap(api.GET('/api/v1/strategy-review', { params: { query: { quarter } } })),
    retry: false,
  })
  const post = useMutation({
    mutationFn: () =>
      unwrap(api.POST('/api/v1/strategy-review/post', { params: { query: { quarter } } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['notifications'] }),
  })
  const data = review.data
  const missing = review.error instanceof ApiProblem && review.error.status === 404
  const pp = (value: string) => `${Number(value) > 0 ? '+' : ''}${num(value, 1)} pp`

  return (
    <div className="space-y-4">
      <Link to="/strategies" className="text-sm hover:underline">
        ← {t('strategyReview.back')}
      </Link>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-semibold">{t('strategyReview.title')}</h1>
        <label className="flex items-center gap-2 text-sm">
          {t('strategyReview.quarter')}
          <Select
            value={quarter}
            onChange={(e) => setParams({ quarter: e.target.value })}
            aria-label={t('strategyReview.quarter')}
          >
            {quarters().map((q) => (
              <option key={q} value={q}>
                {q}
              </option>
            ))}
          </Select>
        </label>
      </div>
      {review.isPending && <p role="status">…</p>}
      {missing && <p className="text-muted">{t('strategyReview.noStrategy')}</p>}
      {review.isError && !missing && <Alert>{errorMessage(review.error)}</Alert>}
      {data && (
        <>
          <p className="text-sm text-muted">
            {data.strategy}, {data.start} – {data.end}.{' '}
            {t('strategyReview.daysWithData', { count: data.days_with_data })}
          </p>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[36rem] text-sm">
              <caption className="sr-only">{t('strategyReview.sleevesCaption')}</caption>
              <thead>
                <tr className="border-b border-border">
                  <th scope="col" className="px-3 py-2 text-left font-medium">
                    {t('strategyReview.sleeve')}
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    {t('strategyReview.target')}
                  </th>
                  <th scope="col" className="px-3 py-2 text-left font-medium">
                    {t('strategyReview.monthEnds')}
                  </th>
                  <th scope="col" className="px-3 py-2 text-left font-medium">
                    {t('strategyReview.furthest')}
                  </th>
                  <th scope="col" className="px-3 py-2 text-left font-medium">
                    {t('strategyReview.outside')}
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.sleeves.map((s) => (
                  <tr key={s.id} className="border-b border-border align-top">
                    <th scope="row" className="px-3 py-2 text-left font-normal">
                      {s.id}
                    </th>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {s.target_pct === null ? (
                        <span className="text-muted">{t('strategyReview.noTarget')}</span>
                      ) : (
                        `${num(s.target_pct, 0)}%`
                      )}
                    </td>
                    <td className="px-3 py-2 tabular-nums">
                      {s.target_pct === null
                        ? '–'
                        : s.month_ends
                            .map((p) => `${p.day.slice(5, 7)}: ${pp(p.drift_pp)}`)
                            .join(' · ')}
                    </td>
                    <td className="px-3 py-2 tabular-nums">
                      {s.worst ? `${pp(s.worst.drift_pp)} (${s.worst.day})` : '–'}
                    </td>
                    <td className="px-3 py-2">
                      {s.target_pct === null
                        ? '–'
                        : t('strategyReview.outsideValue', {
                            hard: s.days_outside_hard,
                            soft: s.days_outside_soft,
                          })}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <section aria-labelledby="rev-signals" className="space-y-1">
            <h2 id="rev-signals" className="text-lg font-medium">
              {t('strategyReview.signals')}
            </h2>
            {data.signals.length === 0 ? (
              <p className="text-muted">{t('strategyReview.noSignals')}</p>
            ) : (
              <ul className="list-disc pl-5 text-sm">
                {data.signals.map((s) => (
                  <li key={s.rule_id}>
                    <strong>{s.rule_id}</strong>:{' '}
                    {t('strategyReview.times', { count: s.count, severity: s.worst_severity })}
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section aria-labelledby="rev-recs" className="space-y-1">
            <h2 id="rev-recs" className="text-lg font-medium">
              {t('strategyReview.recommendations')}
            </h2>
            <p className="text-sm">
              {data.recommendations.made === 0
                ? t('strategyReview.madeNone')
                : t('strategyReview.made', {
                    count: data.recommendations.made,
                    detail: Object.entries(data.recommendations.by_status)
                      .sort(([a], [b]) => a.localeCompare(b))
                      .map(([k, n]) => `${n} ${k}`)
                      .join(', '),
                  })}
            </p>
          </section>
          {data.notes.map((n) => (
            <p key={n} className="text-sm text-muted">
              {n}
            </p>
          ))}
          {data.complete ? (
            <div className="space-y-2">
              <Button onClick={() => post.mutate()} disabled={post.isPending}>
                {t('strategyReview.sendToInbox')}
              </Button>
              {post.isError && <Alert>{errorMessage(post.error)}</Alert>}
              {post.data && (
                <p role="status" className="text-sm">
                  {t(post.data.posted ? 'strategyReview.posted' : 'strategyReview.alreadyPosted')}
                </p>
              )}
            </div>
          ) : (
            <p className="text-sm text-muted">{t('strategyReview.notOver')}</p>
          )}
        </>
      )}
    </div>
  )
}
