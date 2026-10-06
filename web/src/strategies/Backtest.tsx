import { useMutation } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { api, errorMessage, unwrap } from '../api/client'
import { Alert, Button, Field, Input, Select } from '../components/ui'
import { Badge } from '../components/display'
import { useFormat } from '../lib/useFormat'

const TONE = {
  critical: 'bad',
  high: 'bad',
  medium: 'warn',
  low: 'neutral',
  info: 'neutral',
} as const

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

function yearAgo(): string {
  const d = new Date()
  d.setFullYear(d.getFullYear() - 1)
  return d.toISOString().slice(0, 10)
}

/** When would the rules have fired over a range of past days (FR-ST-06)? Nothing is saved. */
export function Backtest({ id, ruleIds }: { id: number; ruleIds: string[] }) {
  const { t } = useTranslation()
  const { num } = useFormat()
  const [rule, setRule] = useState('')
  const [start, setStart] = useState(yearAgo)
  const [end, setEnd] = useState(today)
  const run = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST('/api/v1/strategies/{strategy_id}/backtest', {
          params: { path: { strategy_id: id } },
          body: { rule_ids: rule ? [rule] : null, start, end },
        }),
      ),
  })
  const r = run.data

  function submit(e: FormEvent) {
    e.preventDefault()
    run.mutate()
  }

  return (
    <div className="space-y-4">
      <p className="max-w-2xl text-sm text-muted">{t('backtest.intro')}</p>
      <form
        onSubmit={submit}
        className="flex flex-wrap items-end gap-4"
        aria-label={t('backtest.form')}
      >
        <Field label={t('backtest.rule')}>
          {(p) => (
            <Select value={rule} onChange={(e) => setRule(e.target.value)} {...p}>
              <option value="">{t('backtest.allRules')}</option>
              {ruleIds.map((x) => (
                <option key={x} value={x}>
                  {x}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label={t('backtest.from')}>
          {(p) => (
            <Input type="date" value={start} onChange={(e) => setStart(e.target.value)} {...p} />
          )}
        </Field>
        <Field label={t('backtest.to')}>
          {(p) => <Input type="date" value={end} onChange={(e) => setEnd(e.target.value)} {...p} />}
        </Field>
        <Button type="submit" disabled={run.isPending}>
          {t(run.isPending ? 'backtest.running' : 'backtest.run')}
        </Button>
      </form>
      {run.isError && <Alert>{errorMessage(run.error)}</Alert>}
      {r && (
        <div className="space-y-6">
          <p role="status" className="text-sm">
            {t('backtest.summary', {
              days: r.days_checked,
              count: r.firings.length,
              version: r.version,
            })}
          </p>
          {r.notes.map((n) => (
            <p key={n} className="text-sm text-muted">
              {n}
            </p>
          ))}
          <section aria-labelledby="bt-rules" className="space-y-2">
            <h3 id="bt-rules" className="text-lg font-medium">
              {t('backtest.rules')}
            </h3>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[32rem] text-sm">
                <caption className="sr-only">{t('backtest.rulesCaption')}</caption>
                <thead>
                  <tr className="border-b border-border text-left">
                    <th scope="col" className="px-3 py-2 font-medium">
                      {t('backtest.columns.rule')}
                    </th>
                    <th scope="col" className="px-3 py-2 text-right font-medium">
                      {t('backtest.columns.daysTrue')}
                    </th>
                    <th scope="col" className="px-3 py-2 text-right font-medium">
                      {t('backtest.columns.fired')}
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      {t('backtest.columns.note')}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {r.rules.map((x) => (
                    <tr key={x.rule_id} className="border-b border-border align-top">
                      <th scope="row" className="px-3 py-2 text-left font-normal">
                        {x.rule_id} <span className="text-muted">({x.rule_type})</span>
                      </th>
                      <td className="px-3 py-2 text-right tabular-nums">
                        {x.backtestable ? x.days_true : '–'}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">
                        {x.backtestable ? x.fired : '–'}
                      </td>
                      <td className="px-3 py-2 text-muted">
                        {x.backtestable
                          ? (x.reason ?? '')
                          : `${t('backtest.notBacktestable')} ${x.reason ?? ''}`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
          <section aria-labelledby="bt-firings" className="space-y-2">
            <h3 id="bt-firings" className="text-lg font-medium">
              {t('backtest.firings')}
            </h3>
            {r.firings.length === 0 ? (
              <p className="text-muted">{t('backtest.none')}</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[32rem] text-sm">
                  <caption className="sr-only">{t('backtest.firingsCaption')}</caption>
                  <thead>
                    <tr className="border-b border-border text-left">
                      <th scope="col" className="px-3 py-2 font-medium">
                        {t('backtest.columns.date')}
                      </th>
                      <th scope="col" className="px-3 py-2 font-medium">
                        {t('backtest.columns.rule')}
                      </th>
                      <th scope="col" className="px-3 py-2 font-medium">
                        {t('backtest.columns.what')}
                      </th>
                      <th scope="col" className="px-3 py-2 text-right font-medium">
                        {t('backtest.columns.value')}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {r.firings.map((f, i) => (
                      <tr
                        key={`${f.date}-${f.rule_id}-${f.subject}-${i}`}
                        className="border-b border-border"
                      >
                        <td className="px-3 py-2 whitespace-nowrap tabular-nums">{f.date}</td>
                        <td className="px-3 py-2">
                          {f.rule_id}{' '}
                          <Badge tone={TONE[f.severity as keyof typeof TONE] ?? 'neutral'}>
                            {t(`recs.severity.${f.severity}`, { defaultValue: f.severity })}
                          </Badge>
                        </td>
                        <td className="px-3 py-2">{f.message}</td>
                        <td className="px-3 py-2 text-right tabular-nums">
                          {f.value === null ? '–' : num(f.value, 1)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
          <p className="max-w-2xl text-sm text-muted">{r.note}</p>
        </div>
      )}
    </div>
  )
}
