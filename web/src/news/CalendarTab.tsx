import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../api/client'
import { useInstruments } from '../api/queries'
import { SectionForm } from '../components/SectionForm'
import { Badge, Dialog } from '../components/display'
import { Alert, Button, Field, Input, Select, Textarea } from '../components/ui'
import {
  useCalendarEvents,
  useDeleteEvent,
  useRefreshCalendar,
  useSaveEvent,
  type CalendarEvent,
} from './calendarApi'
import { JobStatus } from '../system/JobStatus'

/** Dated events (FR-NW-09): ready-made central bank decisions, earnings of directly held
 * equities when EODHD provides them, and your own. A brief goes out the evening before. */
export function CalendarTab() {
  const { t } = useTranslation()
  const events = useCalendarEvents()
  const remove = useDeleteEvent()
  const refresh = useRefreshCalendar()
  const [editing, setEditing] = useState<CalendarEvent | 'new' | null>(null)
  const rows = events.data ?? []

  function confirmDelete(e: CalendarEvent) {
    if (window.confirm(t('calendar.deleteConfirm', { title: e.title, date: e.date })))
      remove.mutate(e.id)
  }

  return (
    <div className="space-y-6">
      <section aria-labelledby="cal-upcoming" className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="cal-upcoming" className="text-lg font-semibold">
            {t('calendar.upcoming')}
          </h2>
          <div className="flex gap-2">
            <Button
              variant="secondary"
              onClick={() => refresh.mutate()}
              disabled={refresh.isPending}
            >
              {t('calendar.refresh')}
            </Button>
            <Button onClick={() => setEditing('new')}>{t('calendar.add')}</Button>
          </div>
        </div>
        <JobStatus jobs={['calendar']} from={refresh} />
        {events.isError && <Alert>{errorMessage(events.error)}</Alert>}
        {remove.isError && <Alert>{errorMessage(remove.error)}</Alert>}
        {events.isPending && <p role="status">{t('app.loading')}</p>}
        {events.isSuccess && rows.length === 0 && (
          <p className="text-muted">{t('calendar.empty')}</p>
        )}
        {events.isSuccess && rows.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[36rem] text-sm">
              <caption className="sr-only">{t('calendar.caption')}</caption>
              <thead>
                <tr className="border-b border-border">
                  <th scope="col" className="px-3 py-2 text-left font-medium">
                    {t('calendar.date')}
                  </th>
                  <th scope="col" className="px-3 py-2 text-left font-medium">
                    {t('calendar.event')}
                  </th>
                  <th scope="col" className="px-3 py-2 text-left font-medium">
                    {t('calendar.source')}
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    <span className="sr-only">{t('calendar.actions')}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((e) => (
                  <tr key={e.id} className="border-b border-border align-top">
                    <td className="px-3 py-2 whitespace-nowrap tabular-nums">
                      {e.date}{' '}
                      <span className="text-muted">
                        {e.in_days === 0
                          ? t('calendar.today')
                          : e.in_days > 0
                            ? t('calendar.inDays', { count: e.in_days })
                            : t('calendar.daysAgo', { count: -e.in_days })}
                      </span>
                    </td>
                    <td className="px-3 py-2">
                      <div className="font-medium">{e.title}</div>
                      {e.instrument_name && <div className="text-muted">{e.instrument_name}</div>}
                      {e.detail && <div className="text-muted">{e.detail}</div>}
                    </td>
                    <td className="px-3 py-2">
                      <Badge tone="neutral">{t(`calendar.sources.${e.source}`)}</Badge>
                    </td>
                    <td className="px-3 py-2 text-right whitespace-nowrap">
                      <Button
                        variant="ghost"
                        onClick={() => setEditing(e)}
                        aria-label={t('calendar.edit', { title: e.title })}
                      >
                        {t('calendar.editButton')}
                      </Button>
                      <Button
                        variant="ghost"
                        onClick={() => confirmDelete(e)}
                        aria-label={t('calendar.delete', { title: e.title })}
                      >
                        {t('calendar.deleteButton')}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="text-sm text-muted">{t('calendar.verify')}</p>
      </section>

      <section aria-labelledby="cal-settings" className="space-y-3">
        <h2 id="cal-settings" className="text-lg font-semibold">
          {t('calendar.settings')}
        </h2>
        <p className="text-sm text-muted">{t('calendar.settingsHelp')}</p>
        <SectionForm section="calendar" />
      </section>

      <Dialog
        open={editing !== null}
        onClose={() => setEditing(null)}
        title={t(editing === 'new' ? 'calendar.addTitle' : 'calendar.editTitle')}
      >
        {editing !== null && (
          <EventForm
            key={editing === 'new' ? 'new' : editing.id}
            editing={editing === 'new' ? undefined : editing}
            onDone={() => setEditing(null)}
          />
        )}
      </Dialog>
    </div>
  )
}

function EventForm({ editing, onDone }: { editing?: CalendarEvent; onDone: () => void }) {
  const { t } = useTranslation()
  const instruments = useInstruments('all')
  const save = useSaveEvent()
  const [title, setTitle] = useState(editing?.title ?? '')
  const [day, setDay] = useState(editing?.date ?? '')
  const [instrumentId, setInstrumentId] = useState(
    editing?.instrument_id ? String(editing.instrument_id) : '',
  )
  const [detail, setDetail] = useState(editing?.detail ?? '')
  const [error, setError] = useState('')

  function submit(e: FormEvent) {
    e.preventDefault()
    if (!title.trim() || !day) {
      setError(t('calendar.required'))
      return
    }
    setError('')
    save.mutate(
      {
        id: editing?.id,
        body: {
          title: title.trim(),
          date: day,
          kind: editing?.kind ?? 'custom',
          instrument_id: instrumentId ? Number(instrumentId) : null,
          detail: detail.trim(),
        },
      },
      { onSuccess: onDone },
    )
  }

  return (
    <form onSubmit={submit} className="space-y-4" noValidate aria-label={t('calendar.form')}>
      <Field label={t('calendar.fields.title')} error={error && !title.trim() ? error : undefined}>
        {(p) => <Input value={title} onChange={(e) => setTitle(e.target.value)} {...p} />}
      </Field>
      <Field label={t('calendar.fields.date')} error={error && !day ? error : undefined}>
        {(p) => <Input type="date" value={day} onChange={(e) => setDay(e.target.value)} {...p} />}
      </Field>
      <Field label={t('calendar.fields.instrument')}>
        {(p) => (
          <Select value={instrumentId} onChange={(e) => setInstrumentId(e.target.value)} {...p}>
            <option value="">{t('calendar.fields.none')}</option>
            {(instruments.data ?? []).map((i) => (
              <option key={i.id} value={i.id}>
                {i.name}
              </option>
            ))}
          </Select>
        )}
      </Field>
      <Field label={t('calendar.fields.detail')}>
        {(p) => (
          <Textarea rows={2} value={detail} onChange={(e) => setDetail(e.target.value)} {...p} />
        )}
      </Field>
      {save.isError && <Alert>{errorMessage(save.error)}</Alert>}
      <Button type="submit" disabled={save.isPending}>
        {t('calendar.save')}
      </Button>
    </form>
  )
}
