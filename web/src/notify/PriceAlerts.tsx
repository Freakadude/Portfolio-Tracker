import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { api, errorMessage, unwrap } from '../api/client'
import { Badge } from '../components/display'
import { Alert, Button, Field, Input, Select } from '../components/ui'
import { isPositiveDecimal } from '../lib/decimal'
import { useAlerts } from './api'

/** Price alerts on one instrument (FR-INS-05): above or below a price in its trading currency.
 * An alert fires once when a close crosses the level and re-arms when the price is back. */
export function PriceAlerts({ instrumentId, name }: { instrumentId: number; name: string }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const alerts = useAlerts(instrumentId)
  const [condition, setCondition] = useState<'above' | 'below'>('above')
  const [threshold, setThreshold] = useState('')
  const [note, setNote] = useState('')
  const [problem, setProblem] = useState<string>()
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['price-alerts'] })
  const add = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST('/api/v1/price-alerts', {
          body: {
            instrument_id: instrumentId,
            condition,
            threshold: threshold.trim().replace(',', '.'),
            note: note.trim() || null,
          },
        }),
      ),
    onSuccess: async () => {
      setThreshold('')
      setNote('')
      await refresh()
    },
  })
  const change = useMutation({
    mutationFn: ({ id, active }: { id: number; active: boolean }) =>
      unwrap(
        api.PATCH('/api/v1/price-alerts/{alert_id}', {
          params: { path: { alert_id: id } },
          body: { active },
        }),
      ),
    onSuccess: refresh,
  })
  const remove = useMutation({
    mutationFn: (id: number) =>
      unwrap(api.DELETE('/api/v1/price-alerts/{alert_id}', { params: { path: { alert_id: id } } })),
    onSuccess: refresh,
  })
  function submit(e: FormEvent) {
    e.preventDefault()
    if (!isPositiveDecimal(threshold)) return setProblem(t('alerts.thresholdRequired'))
    setProblem(undefined)
    add.mutate()
  }
  const rows = alerts.data ?? []
  return (
    <section aria-label={t('alerts.title', { name })} className="space-y-2">
      <h3 className="font-medium">{t('alerts.heading')}</h3>
      {rows.length > 0 && (
        <ul className="space-y-1 text-sm">
          {rows.map((a) => (
            <li key={a.id} className="flex flex-wrap items-center gap-2">
              <span>
                {t(`alerts.conditions.${a.condition}`)} {a.threshold} {a.currency ?? ''}
              </span>
              {!a.active ? (
                <Badge>{t('alerts.paused')}</Badge>
              ) : a.armed ? (
                <Badge tone="good">{t('alerts.armed')}</Badge>
              ) : (
                <Badge tone="warn">{t('alerts.fired')}</Badge>
              )}
              {a.note && <span className="text-muted">{a.note}</span>}
              <Button
                variant="ghost"
                className="min-h-8 px-2"
                onClick={() => change.mutate({ id: a.id, active: !a.active })}
              >
                {t(a.active ? 'alerts.pause' : 'alerts.resume')}
              </Button>
              <Button
                variant="ghost"
                className="min-h-8 px-2"
                aria-label={t('alerts.deleteLabel', {
                  condition: t(`alerts.conditions.${a.condition}`),
                  threshold: a.threshold,
                })}
                onClick={() => remove.mutate(a.id)}
              >
                {t('alerts.delete')}
              </Button>
            </li>
          ))}
        </ul>
      )}
      <form onSubmit={submit} className="flex flex-wrap items-end gap-2" noValidate>
        <Field label={t('alerts.condition')}>
          {(p) => (
            <Select
              value={condition}
              onChange={(e) => setCondition(e.target.value as 'above' | 'below')}
              {...p}
            >
              <option value="above">{t('alerts.conditions.above')}</option>
              <option value="below">{t('alerts.conditions.below')}</option>
            </Select>
          )}
        </Field>
        <Field label={t('alerts.threshold')} error={problem}>
          {(p) => (
            <Input
              className="w-28"
              inputMode="decimal"
              value={threshold}
              onChange={(e) => setThreshold(e.target.value)}
              {...p}
            />
          )}
        </Field>
        <Field label={t('alerts.note')}>
          {(p) => (
            <Input
              className="w-56"
              maxLength={200}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              {...p}
            />
          )}
        </Field>
        <Button type="submit" variant="secondary" disabled={add.isPending}>
          {t('alerts.add')}
        </Button>
      </form>
      {(add.error ?? change.error ?? remove.error) && (
        <Alert>{errorMessage(add.error ?? change.error ?? remove.error)}</Alert>
      )}
    </section>
  )
}
