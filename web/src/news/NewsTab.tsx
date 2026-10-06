import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../api/client'
import { SectionForm } from '../components/SectionForm'
import { Badge } from '../components/display'
import { Alert, Button, Checkbox, Field, Help, Input, Select } from '../components/ui'
import {
  useDeleteNewsSource,
  useFetchNow,
  useNewsSources,
  usePreviewFeed,
  useSaveNewsSource,
  type NewsSource,
  type NewsSourceInput,
} from './api'
import { JobStatus } from '../system/JobStatus'

const EMPTY: NewsSourceInput = {
  name: '',
  kind: 'rss',
  url: '',
  language: 'en',
  trust_weight: '0.7',
  poll_minutes: 60,
  enabled: true,
  macro_series: [],
}

/** Settings, News: the list of sources (central banks and EODHD come ready, you add issuers'
 * feeds), a preview of a feed before it is saved, each source's fetch status, and how stories
 * are triaged (FR-NW-01, FR-NW-02). */
export function NewsTab() {
  const { t } = useTranslation()
  const sources = useNewsSources()
  const remove = useDeleteNewsSource()
  const fetchNow = useFetchNow()
  const [editing, setEditing] = useState<{ id?: number; value: NewsSourceInput } | null>(null)
  return (
    <div className="space-y-6">
      <Help title={t('newsSettings.helpTitle')}>
        <p>{t('newsSettings.help1')}</p>
        <p>{t('newsSettings.help2')}</p>
        <p>{t('newsSettings.help3')}</p>
      </Help>
      <p className="text-sm text-muted">{t('newsSettings.intro')}</p>
      {sources.isError && <Alert>{errorMessage(sources.error)}</Alert>}
      {remove.isError && <Alert>{errorMessage(remove.error)}</Alert>}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <caption className="sr-only">{t('newsSettings.caption')}</caption>
          <thead>
            <tr className="border-b border-border text-left">
              {(['name', 'kind', 'last', 'status', 'actions'] as const).map((c) => (
                <th key={c} scope="col" className="py-1 pr-3 font-medium">
                  {t(`newsSettings.columns.${c}`)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sources.data?.map((s) => (
              <SourceRow
                key={s.id}
                source={s}
                onEdit={() =>
                  setEditing({
                    id: s.id,
                    value: {
                      name: s.name,
                      kind: s.kind,
                      url: s.url,
                      language: s.language,
                      trust_weight: s.trust_weight,
                      poll_minutes: s.poll_minutes,
                      enabled: s.enabled,
                      macro_series: s.macro_series,
                    },
                  })
                }
                onDelete={() => {
                  if (window.confirm(t('newsSettings.deleteConfirm', { name: s.name })))
                    remove.mutate(s.id)
                }}
                onFetch={() => fetchNow.mutate(s.id)}
              />
            ))}
          </tbody>
        </table>
      </div>
      <JobStatus jobs={['news']} from={fetchNow} />
      {fetchNow.isError && <Alert>{errorMessage(fetchNow.error)}</Alert>}
      {editing ? (
        <SourceForm
          key={editing.id ?? 'new'}
          id={editing.id}
          initial={editing.value}
          onDone={() => setEditing(null)}
        />
      ) : (
        <Button variant="secondary" onClick={() => setEditing({ value: EMPTY })}>
          {t('newsSettings.add')}
        </Button>
      )}
      <h3 className="font-medium">{t('newsSettings.triage')}</h3>
      <SectionForm section="news" />
    </div>
  )
}

function SourceRow({
  source,
  onEdit,
  onDelete,
  onFetch,
}: {
  source: NewsSource
  onEdit: () => void
  onDelete: () => void
  onFetch: () => void
}) {
  const { t } = useTranslation()
  return (
    <tr className="border-b border-border align-top">
      <td className="py-2 pr-3">
        {source.name}
        {!source.enabled && (
          <span className="ml-1 text-xs text-muted">({t('newsSettings.off')})</span>
        )}
        <div className="text-xs text-muted">
          {t('newsSettings.trust', { trust: source.trust_weight })}
          {source.macro_series.length > 0 && ` · ${source.macro_series.join(', ')}`}
        </div>
      </td>
      <td className="py-2 pr-3">{t(`newsSettings.kinds.${source.kind}`)}</td>
      <td className="py-2 pr-3 whitespace-nowrap">
        {source.last_fetch_at ? new Date(source.last_fetch_at).toLocaleString() : '–'}
        <div className="text-xs text-muted">{t('newsSettings.items', { count: source.items })}</div>
      </td>
      <td className="py-2 pr-3">
        {source.failures > 0 ? (
          <div className="space-y-1">
            <Badge tone="bad">{t('newsSettings.failing', { count: source.failures })}</Badge>
            <p className="text-xs">{source.last_error}</p>
          </div>
        ) : (
          <Badge tone="good">{t('newsSettings.ok')}</Badge>
        )}
      </td>
      <td className="py-2 whitespace-nowrap">
        <Button
          variant="secondary"
          onClick={onFetch}
          aria-label={`${t('newsSettings.fetch')} ${source.name}`}
        >
          {t('newsSettings.fetch')}
        </Button>{' '}
        <Button
          variant="secondary"
          onClick={onEdit}
          aria-label={`${t('newsSettings.edit')} ${source.name}`}
        >
          {t('newsSettings.edit')}
        </Button>{' '}
        <Button
          variant="secondary"
          onClick={onDelete}
          aria-label={`${t('newsSettings.delete')} ${source.name}`}
        >
          {t('newsSettings.delete')}
        </Button>
      </td>
    </tr>
  )
}

function SourceForm({
  id,
  initial,
  onDone,
}: {
  id?: number
  initial: NewsSourceInput
  onDone: () => void
}) {
  const { t } = useTranslation()
  const save = useSaveNewsSource()
  const preview = usePreviewFeed()
  const [v, setV] = useState(initial)
  const feed = v.kind === 'rss'
  return (
    <form
      className="space-y-3 rounded-md border border-border p-4"
      aria-label={id === undefined ? t('newsSettings.add') : t('newsSettings.edit')}
      onSubmit={(e) => {
        e.preventDefault()
        save.mutate({ id, body: v }, { onSuccess: onDone })
      }}
    >
      <Field label={t('newsSettings.form.name')}>
        {(p) => (
          <Input value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} {...p} />
        )}
      </Field>
      {feed && (
        <Field label={t('newsSettings.form.url')}>
          {(p) => (
            <div className="flex gap-2">
              <Input value={v.url} onChange={(e) => setV({ ...v, url: e.target.value })} {...p} />
              <Button
                variant="secondary"
                onClick={() => preview.mutate(v.url)}
                disabled={preview.isPending || !v.url}
              >
                {t('newsSettings.form.preview')}
              </Button>
            </div>
          )}
        </Field>
      )}
      {preview.isError && <Alert>{errorMessage(preview.error)}</Alert>}
      {preview.data && (
        <div className="space-y-1" role="status">
          <p className="text-sm font-medium">
            {t('newsSettings.form.previewIntro', {
              shown: preview.data.items.length,
              total: preview.data.total,
            })}
          </p>
          <ul className="space-y-0.5 text-sm">
            {preview.data.items.map((i) => (
              <li key={i.url}>
                <span className="text-muted">{new Date(i.published).toLocaleDateString()}: </span>
                {i.title}
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label={t('newsSettings.form.language')}>
          {(p) => (
            <Input
              value={v.language ?? 'en'}
              onChange={(e) => setV({ ...v, language: e.target.value })}
              {...p}
            />
          )}
        </Field>
        <Field label={t('newsSettings.form.trust')} hint={t('newsSettings.form.trustHint')}>
          {(p) => (
            <Input
              inputMode="decimal"
              value={String(v.trust_weight ?? '')}
              onChange={(e) => setV({ ...v, trust_weight: e.target.value })}
              {...p}
            />
          )}
        </Field>
        <Field label={t('newsSettings.form.poll')}>
          {(p) => (
            <Select
              value={v.poll_minutes ?? 60}
              onChange={(e) => setV({ ...v, poll_minutes: Number(e.target.value) })}
              {...p}
            >
              {[15, 30, 60, 180, 360, 720, 1440].map((m) => (
                <option key={m} value={m}>
                  {t('newsSettings.form.every', { minutes: m })}
                </option>
              ))}
            </Select>
          )}
        </Field>
      </div>
      <Field label={t('newsSettings.form.macro')} hint={t('newsSettings.form.macroHint')}>
        {(p) => (
          <Input
            value={(v.macro_series ?? []).join(', ')}
            onChange={(e) =>
              setV({
                ...v,
                macro_series: e.target.value
                  .split(',')
                  .map((x) => x.trim())
                  .filter(Boolean),
              })
            }
            {...p}
          />
        )}
      </Field>
      <Checkbox
        label={t('newsSettings.form.enabled')}
        checked={v.enabled ?? true}
        onChange={(e) => setV({ ...v, enabled: e.target.checked })}
      />
      {save.isError && <Alert>{errorMessage(save.error)}</Alert>}
      <div className="flex gap-2">
        <Button type="submit" disabled={save.isPending}>
          {t('app.save')}
        </Button>
        <Button variant="secondary" onClick={onDone}>
          {t('newsSettings.form.cancel')}
        </Button>
      </div>
    </form>
  )
}
