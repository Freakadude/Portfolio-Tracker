import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { api, errorMessage, unwrap } from '../api/client'
import { Dialog } from '../components/display'
import { Alert, Button, Field, Help, Input } from '../components/ui'
import { useFormat } from '../lib/useFormat'

type Item = {
  job_id: string
  title: string
  what: string
  normal: string
  normal_cron: string
  cron: string
  changed: boolean
  timezone: string
  next_run: string | null
}

/** Settings, Schedules (FR-SY-09): every background job with what it does and when it runs, and
 * a way to move one to another time, with examples of how to write a time. */
export function SchedulesTab() {
  const { t } = useTranslation()
  const { when } = useFormat()
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState<Item | null>(null)
  const list = useQuery({
    queryKey: ['schedules'],
    queryFn: () => unwrap(api.GET('/api/v1/schedules')),
  })
  const reset = useMutation({
    mutationFn: (jobId: string) =>
      unwrap(
        api.PUT('/api/v1/schedules/{job_id}', {
          params: { path: { job_id: jobId } },
          body: { cron: null },
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['schedules'] }),
  })
  const data = list.data
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted">{t('schedules.intro')}</p>
      <Help title={t('schedules.helpTitle')}>
        <p>{t('schedules.help1')}</p>
        <p>{t('schedules.help2')}</p>
        <ul className="list-disc pl-5">
          {data?.examples.map(({ cron, words }) => (
            <li key={cron}>
              <code className="rounded bg-border/40 px-1">{cron}</code>: {words}
            </li>
          ))}
        </ul>
        <p>{t('schedules.help3', { zone: data?.timezone ?? '' })}</p>
      </Help>
      {list.isError && <Alert>{errorMessage(list.error)}</Alert>}
      {reset.isError && <Alert>{errorMessage(reset.error)}</Alert>}
      {list.isPending ? (
        <p role="status">{t('app.loading')}</p>
      ) : (
        data && (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <caption className="sr-only">{t('schedules.caption')}</caption>
                <thead>
                  <tr className="border-b border-border text-left">
                    {(['job', 'normal', 'now', 'next', 'actions'] as const).map((c) => (
                      <th key={c} scope="col" className="py-2 pr-3 font-medium">
                        {t(`schedules.columns.${c}`)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((i) => (
                    <tr key={i.job_id} className="border-b border-border align-top">
                      <td className="py-2 pr-3">
                        <div className="font-medium">{i.title}</div>
                        <div className="max-w-md text-xs text-muted">{i.what}</div>
                      </td>
                      <td className="py-2 pr-3">{i.normal}</td>
                      <td className="py-2 pr-3">
                        {i.changed ? (
                          <>
                            <code className="rounded bg-border/40 px-1">{i.cron}</code>
                            <div className="text-xs text-muted">{t('schedules.changed')}</div>
                          </>
                        ) : (
                          <span className="text-muted">{t('schedules.asNormal')}</span>
                        )}
                      </td>
                      <td className="py-2 pr-3 whitespace-nowrap">{when(i.next_run)}</td>
                      <td className="py-2 whitespace-nowrap">
                        <Button
                          variant="ghost"
                          onClick={() => setEditing(i)}
                          aria-label={t('schedules.change', { name: i.title })}
                        >
                          {t('schedules.changeShort')}
                        </Button>
                        {i.changed && (
                          <Button
                            variant="ghost"
                            disabled={reset.isPending}
                            onClick={() => reset.mutate(i.job_id)}
                            aria-label={t('schedules.putBack', { name: i.title })}
                          >
                            {t('schedules.putBackShort')}
                          </Button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="space-y-1 text-sm text-muted">
              <p className="font-medium text-foreground">{t('schedules.fixedTitle')}</p>
              <ul className="list-disc pl-5">
                {data.fixed.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </div>
          </>
        )
      )}
      {editing && data && (
        <Dialog
          open
          onClose={() => setEditing(null)}
          title={t('schedules.editTitle', { name: editing.title })}
        >
          <ScheduleForm
            item={editing}
            examples={data.examples}
            zone={editing.timezone}
            onDone={async () => {
              await queryClient.invalidateQueries({ queryKey: ['schedules'] })
              setEditing(null)
            }}
          />
        </Dialog>
      )}
    </div>
  )
}

function ScheduleForm({
  item,
  examples,
  zone,
  onDone,
}: {
  item: Item
  examples: { cron: string; words: string }[]
  zone: string
  onDone: () => void
}) {
  const { t } = useTranslation()
  const [cron, setCron] = useState(item.cron)
  const save = useMutation({
    mutationFn: () =>
      unwrap(
        api.PUT('/api/v1/schedules/{job_id}', {
          params: { path: { job_id: item.job_id } },
          body: { cron },
        }),
      ),
    onSuccess: onDone,
  })
  function submit(e: FormEvent) {
    e.preventDefault()
    save.mutate()
  }
  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <p className="text-sm text-muted">{item.what}</p>
      <p className="text-sm">{t('schedules.normallyRuns', { when: item.normal })}</p>
      <Field label={t('schedules.cronLabel')} hint={t('schedules.cronHint', { zone })}>
        {(p) => (
          <Input
            value={cron}
            onChange={(e) => setCron(e.target.value)}
            className="font-mono"
            spellCheck={false}
            {...p}
          />
        )}
      </Field>
      <div className="space-y-1">
        <p className="text-sm font-medium">{t('schedules.tryOne')}</p>
        <div className="flex flex-wrap gap-2">
          {examples.map(({ cron: text, words }) => (
            <Button key={text} type="button" variant="secondary" onClick={() => setCron(text)}>
              {words}
            </Button>
          ))}
          <Button type="button" variant="ghost" onClick={() => setCron(item.normal_cron)}>
            {t('schedules.useNormal')}
          </Button>
        </div>
      </div>
      {save.isError && <Alert>{errorMessage(save.error)}</Alert>}
      <Button type="submit" disabled={save.isPending}>
        {t('schedules.save')}
      </Button>
    </form>
  )
}
