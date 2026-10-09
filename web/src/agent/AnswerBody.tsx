import { useTranslation } from 'react-i18next'
import { Alert } from '../components/ui'
import { useFormat } from '../lib/useFormat'
import type { Question } from './api'

/** What came back for a question (FR-AG-08): the answer, what could not be found, why an answer
 * was held back, and the data it rests on. Shared by the Ask box and the chat side panel. */
export function AnswerBody({ q, compact = false }: { q: Question; compact?: boolean }) {
  const { t } = useTranslation()
  const { rounded, smallEur } = useFormat()
  const finished = q.status !== 'queued' && q.status !== 'running'
  const cost = Number(q.cost_eur)
  return (
    <>
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
                  {rounded(d.result)}
                </pre>
              </li>
            ))}
          </ul>
        </details>
      )}
      <p className="text-xs text-muted">
        {q.ai_label}
        {finished && cost > 0 && (
          <>
            {' '}
            <span data-testid="answer-cost">{t('ask.cost', { amount: smallEur(q.cost_eur) })}</span>
          </>
        )}
      </p>
    </>
  )
}
