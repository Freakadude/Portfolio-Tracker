import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../api/client'
import { Badge } from '../components/display'
import { Alert, Button } from '../components/ui'
import { useFormat } from '../lib/useFormat'
import { useAgentRun, useAgentRuns, type AgentRun } from './api'

const TONE = { ok: 'good', failed: 'bad', budget: 'warn', running: 'neutral' } as const

/** System page: the agent's runs with what each cost, and the full trace of one (spec section
 * 11, traceability): the context pack it was given, every tool call, its findings, its raw answer
 * and the verdict on each recommendation, refused ones with their reasons. */
export function RunsPanel() {
  const { t } = useTranslation()
  const runs = useAgentRuns()
  const [open, setOpen] = useState<number | null>(null)
  return (
    <section aria-labelledby="runs-h" className="space-y-3">
      <h2 id="runs-h" className="text-lg font-semibold">
        {t('runs.title')}
      </h2>
      {runs.isError && <Alert>{errorMessage(runs.error)}</Alert>}
      {runs.isSuccess && runs.data.length === 0 && <p className="text-muted">{t('runs.empty')}</p>}
      {runs.data && runs.data.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <caption className="sr-only">{t('runs.caption')}</caption>
            <thead>
              <tr className="border-b border-border text-left">
                {(['when', 'what', 'status', 'items', 'cost', 'actions'] as const).map((c) => (
                  <th key={c} scope="col" className="py-1 pr-3 font-medium">
                    {t(`runs.columns.${c}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {runs.data.map((r) => (
                <RunRow key={r.id} run={r} onOpen={() => setOpen(open === r.id ? null : r.id)} />
              ))}
            </tbody>
          </table>
        </div>
      )}
      {open !== null && <Trace id={open} />}
    </section>
  )
}

function RunRow({ run, onOpen }: { run: AgentRun; onOpen: () => void }) {
  const { t } = useTranslation()
  const { smallEur } = useFormat()
  return (
    <tr className="border-b border-border align-top">
      <td className="py-1 pr-3 whitespace-nowrap">{new Date(run.started_at).toLocaleString()}</td>
      <td className="py-1 pr-3">
        {t(`runs.type.${run.run_type}`, { defaultValue: run.run_type })}
        <div className="text-xs text-muted">{run.model}</div>
      </td>
      <td className="py-1 pr-3">
        <Badge tone={TONE[run.status as keyof typeof TONE] ?? 'neutral'}>
          {t(`runs.status.${run.status}`, { defaultValue: run.status })}
        </Badge>
        {run.error && <div className="text-xs text-muted">{run.error}</div>}
      </td>
      <td className="py-1 pr-3 tabular-nums">
        {t('runs.items', { made: run.recommendations, refused: run.refused })}
      </td>
      <td className="py-1 pr-3 tabular-nums">{smallEur(run.cost_eur)}</td>
      <td className="py-1">
        <Button variant="secondary" onClick={onOpen} aria-label={`${t('runs.trace')} ${run.id}`}>
          {t('runs.trace')}
        </Button>
      </td>
    </tr>
  )
}

function Trace({ id }: { id: number }) {
  const { t } = useTranslation()
  const run = useAgentRun(id)
  if (run.isPending) return <p role="status">{t('app.loading')}</p>
  if (run.isError) return <Alert>{errorMessage(run.error)}</Alert>
  const r = run.data
  const verdicts = (r.output.verdicts ?? []) as {
    index: number
    accepted: boolean
    reasons: string[]
  }[]
  return (
    <div
      className="space-y-3 rounded-md border border-border p-4"
      role="region"
      aria-label={`${t('runs.trace')} ${id}`}
    >
      <p className="text-sm">
        {t('runs.tokens', {
          input: r.input_tokens,
          output: r.output_tokens,
          cached: r.cache_read_tokens,
          searches: r.web_searches,
        })}
      </p>
      <p className="text-xs text-muted">{t('runs.prompts', { labels: r.prompt_version })}</p>
      {r.digest && <p className="text-sm">{r.digest}</p>}
      {r.items.length > 0 && (
        <ul className="space-y-1 text-sm" aria-label={t('runs.verdicts')}>
          {r.items.map((i) => {
            const verdict = verdicts.find((v) => v.index === r.items.indexOf(i))
            return (
              <li key={i.id}>
                <Badge tone={i.status === 'refused' ? 'bad' : 'good'}>
                  {i.status === 'refused' ? t('runs.refused') : t('runs.shown')}
                </Badge>{' '}
                {i.title}
                {i.refused_reason && <div className="text-xs text-muted">{i.refused_reason}</div>}
                {!i.refused_reason && verdict && verdict.reasons.length > 0 && (
                  <div className="text-xs text-muted">{verdict.reasons.join('; ')}</div>
                )}
              </li>
            )
          })}
        </ul>
      )}
      <details>
        <summary className="cursor-pointer text-sm">
          {t('runs.toolCalls', { count: r.tool_calls.length })}
        </summary>
        <ol className="mt-1 space-y-1 text-xs">
          {r.tool_calls.map((c, n) => (
            <li key={n}>
              <code>{String(c.name)}</code> <code>{JSON.stringify(c.input)}</code>
              {c.error === true && <span className="text-danger"> ({t('runs.errored')})</span>}
            </li>
          ))}
        </ol>
      </details>
      <details>
        <summary className="cursor-pointer text-sm">{t('runs.findings')}</summary>
        <pre className="mt-1 max-h-72 overflow-auto whitespace-pre-wrap text-xs">{r.findings}</pre>
      </details>
      <details>
        <summary className="cursor-pointer text-sm">{t('runs.context')}</summary>
        <pre className="mt-1 max-h-72 overflow-auto whitespace-pre-wrap text-xs">
          {JSON.stringify(r.context, null, 2)}
        </pre>
      </details>
      <details>
        <summary className="cursor-pointer text-sm">{t('runs.answer')}</summary>
        <pre className="mt-1 max-h-72 overflow-auto whitespace-pre-wrap text-xs">
          {String(r.output.text ?? '')}
        </pre>
      </details>
    </div>
  )
}
