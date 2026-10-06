import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../api/client'
import { Badge } from '../components/display'
import { Alert, Button, Field, Textarea } from '../components/ui'
import { useAsk, useQuestion, useRecentQuestions, type Question } from './api'

const WORKING = ['queued', 'running']

/** A question box for the agent and its answers (FR-AG-08, FR-DB-09). The agent only reads: its
 * answer is shown only if every figure in it is one its tools returned, and the data it used is
 * listed under it. With an `instrumentId` it analyses that position. */
export function AskPanel({
  instrumentId,
  showLast = 3,
}: {
  instrumentId?: number
  showLast?: number
}) {
  const { t } = useTranslation()
  const ask = useAsk()
  const [text, setText] = useState('')
  const [runId, setRunId] = useState<number | null>(null)
  const current = useQuestion(runId)
  const recent = useRecentQuestions(showLast + 1, instrumentId)
  const working = ask.isPending || (current.data ? WORKING.includes(current.data.status) : false)

  function submit(e: FormEvent) {
    e.preventDefault()
    ask.mutate(
      { question: text.trim() || undefined, instrumentId },
      {
        onSuccess: (queued) => {
          setRunId(queued.run_id)
          setText('')
        },
      },
    )
  }

  const earlier = (recent.data ?? []).filter((q) => q.id !== runId).slice(0, showLast)

  return (
    <div className="space-y-4">
      <form onSubmit={submit} className="space-y-2" aria-label={t('ask.form')}>
        <Field label={t(instrumentId ? 'ask.questionAbout' : 'ask.question')}>
          {(p) => (
            <Textarea
              rows={2}
              maxLength={500}
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={t(instrumentId ? 'ask.placeholderPosition' : 'ask.placeholder')}
              {...p}
            />
          )}
        </Field>
        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" disabled={working || (!instrumentId && text.trim().length < 3)}>
            {t(instrumentId && !text.trim() ? 'ask.analyse' : 'ask.send')}
          </Button>
          <span className="text-xs text-muted">{t('ask.readOnly')}</span>
        </div>
      </form>
      {ask.isError && <Alert>{errorMessage(ask.error)}</Alert>}
      {current.isError && <Alert>{errorMessage(current.error)}</Alert>}
      {working && (
        <p role="status" className="text-sm text-muted">
          {t('ask.working')}
        </p>
      )}
      {current.data && !working && <Answer q={current.data} />}
      {earlier.length > 0 && (
        <section aria-label={t('ask.earlier')} className="space-y-3">
          <h3 className="text-sm font-medium">{t('ask.earlier')}</h3>
          {earlier.map((q) => (
            <Answer key={q.id} q={q} compact />
          ))}
        </section>
      )}
    </div>
  )
}

function Answer({ q, compact = false }: { q: Question; compact?: boolean }) {
  const { t } = useTranslation()
  return (
    <article aria-label={q.question} className="space-y-2 rounded-md border border-border p-3">
      <header className="flex flex-wrap items-center gap-2">
        <p className="font-medium">{q.question}</p>
        <Badge>{t('recs.ai')}</Badge>
      </header>
      {q.answer && <p className="whitespace-pre-line text-sm">{q.answer}</p>}
      {q.not_found && (
        <p className="text-sm text-muted">
          {t('ask.notFound')} {q.not_found}
        </p>
      )}
      {q.refused && (
        <Alert>
          <p>{t('ask.refused')}</p>
          <ul className="list-disc pl-5">
            {q.reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </Alert>
      )}
      {q.status === 'failed' && <Alert>{q.error ?? t('ask.failed')}</Alert>}
      {q.status === 'budget' && <Alert>{q.error ?? t('ask.budget')}</Alert>}
      {WORKING.includes(q.status) && <p className="text-sm text-muted">{t('ask.working')}</p>}
      {q.data.length > 0 && (
        <details open={!compact}>
          <summary className="cursor-pointer text-sm font-medium">
            {t('ask.dataUsed', { count: q.data.length })}
          </summary>
          <ul className="mt-2 space-y-2 text-sm">
            {q.data.map((d, i) => (
              <li key={`${d.tool}-${i}`}>
                <div>
                  <code>{d.tool}</code> <span className="text-muted">{d.note}</span>
                </div>
                <pre className="mt-1 max-h-48 overflow-auto rounded bg-card p-2 text-xs whitespace-pre-wrap">
                  {d.result}
                </pre>
              </li>
            ))}
          </ul>
        </details>
      )}
      <p className="text-xs text-muted">{q.ai_label}</p>
    </article>
  )
}
