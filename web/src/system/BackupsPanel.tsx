import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { api, errorMessage, unwrap } from '../api/client'
import { Badge, Dialog } from '../components/display'
import { Alert, Button, Checkbox, Field, Input } from '../components/ui'

const KEY = ['system', 'backups'] as const
const STATUS = ['system', 'restore'] as const

function size(bytes: number): string {
  return bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1)} MB` : `${Math.ceil(bytes / 1024)} kB`
}

/** Backups on the server and restoring one (FR-SY-07). A restore is staged and applied when
 * Folio restarts, so the running database is never swapped under it. */
export function BackupsPanel() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const list = useQuery({
    queryKey: KEY,
    queryFn: () => unwrap(api.GET('/api/v1/system/backups')),
  })
  const status = useQuery({
    queryKey: STATUS,
    queryFn: () => unwrap(api.GET('/api/v1/system/restore')),
  })
  const [withKeys, setWithKeys] = useState(true)
  const [chosen, setChosen] = useState<string | null>(null)
  const refresh = () => queryClient.invalidateQueries({ queryKey: KEY })
  const make = useMutation({
    mutationFn: () =>
      unwrap(api.POST('/api/v1/system/backups', { body: { include_secrets: withKeys } })),
    onSuccess: refresh,
  })
  const remove = useMutation({
    mutationFn: (name: string) =>
      unwrap(api.DELETE('/api/v1/system/backups/{name}', { params: { path: { name } } })),
    onSuccess: refresh,
  })
  const last = status.data?.last

  return (
    <section className="space-y-3" aria-labelledby="backups-title">
      <h2 id="backups-title" className="text-lg font-semibold">
        {t('backups.title')}
      </h2>
      <p className="max-w-2xl text-sm text-muted">{t('backups.intro')}</p>
      {last && (
        <Alert>
          {last.ok
            ? t('backups.lastOk', { source: last.source, at: new Date(last.at).toLocaleString() })
            : t('backups.lastFailed', { source: last.source, error: last.error ?? '' })}
        </Alert>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={() => make.mutate()} disabled={make.isPending}>
          {t('backups.now')}
        </Button>
        <Checkbox
          label={t('backups.withKeys')}
          checked={withKeys}
          onChange={(e) => setWithKeys(e.target.checked)}
        />
      </div>
      {make.isError && <Alert>{errorMessage(make.error)}</Alert>}
      {remove.isError && <Alert>{errorMessage(remove.error)}</Alert>}
      {list.isError && <Alert>{errorMessage(list.error)}</Alert>}
      {list.isSuccess && list.data.length === 0 && (
        <p className="text-muted">{t('backups.none')}</p>
      )}
      {list.isSuccess && list.data.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[34rem] text-sm">
            <caption className="sr-only">{t('backups.caption')}</caption>
            <thead>
              <tr className="border-b border-border text-left">
                <th scope="col" className="py-2 pr-3 font-medium">
                  {t('backups.columns.file')}
                </th>
                <th scope="col" className="py-2 pr-3 font-medium">
                  {t('backups.columns.made')}
                </th>
                <th scope="col" className="py-2 pr-3 text-right font-medium">
                  {t('backups.columns.size')}
                </th>
                <th scope="col" className="py-2 text-right font-medium">
                  <span className="sr-only">{t('backups.columns.actions')}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {(list.data ?? []).map((b) => (
                <tr key={b.name} className="border-b border-border align-top">
                  <th scope="row" className="py-2 pr-3 text-left font-normal">
                    {b.name} <Badge tone="neutral">{t(`backups.kinds.${b.kind}`)}</Badge>
                  </th>
                  <td className="py-2 pr-3 whitespace-nowrap">
                    {new Date(b.created_at).toLocaleString()}
                  </td>
                  <td className="py-2 pr-3 text-right tabular-nums">{size(b.size)}</td>
                  <td className="py-2 text-right whitespace-nowrap">
                    <a
                      href={`/api/v1/system/backups/${b.name}`}
                      download
                      aria-label={t('backups.downloadFor', { name: b.name })}
                      className="mr-1 inline-flex min-h-10 items-center rounded-md px-3 text-sm font-medium hover:bg-border/40"
                    >
                      {t('backups.download')}
                    </a>
                    <Button
                      variant="ghost"
                      onClick={() => setChosen(b.name)}
                      aria-label={t('backups.restoreFor', { name: b.name })}
                    >
                      {t('backups.restore')}
                    </Button>
                    <Button
                      variant="ghost"
                      onClick={() => {
                        if (window.confirm(t('backups.deleteConfirm', { name: b.name })))
                          remove.mutate(b.name)
                      }}
                      aria-label={t('backups.deleteFor', { name: b.name })}
                    >
                      {t('backups.delete')}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="text-sm text-muted">{t('backups.downloadNote')}</p>
      <Upload onDone={(name) => setChosen(name)} refresh={refresh} />
      <RestoreDialog name={chosen} onClose={() => setChosen(null)} />
    </section>
  )
}

function Upload({ onDone, refresh }: { onDone: (name: string) => void; refresh: () => unknown }) {
  const { t } = useTranslation()
  const [file, setFile] = useState<File | null>(null)
  const [missing, setMissing] = useState(false)
  const upload = useMutation({
    mutationFn: (f: File) => {
      const data = new FormData()
      data.set('file', f)
      return unwrap(
        api.POST('/api/v1/system/backups/upload', {
          body: {} as never,
          bodySerializer: () => data,
        }),
      )
    },
    onSuccess: (made) => {
      void refresh()
      setFile(null)
      onDone(made.name)
    },
  })

  function submit(e: FormEvent) {
    e.preventDefault()
    if (!file) return setMissing(true)
    setMissing(false)
    upload.mutate(file)
  }

  return (
    <form
      onSubmit={submit}
      className="max-w-lg space-y-2 rounded-md border border-border p-4"
      aria-label={t('backups.upload.title')}
    >
      <h3 className="font-medium">{t('backups.upload.title')}</h3>
      <p className="text-sm text-muted">{t('backups.upload.help')}</p>
      <Field label={t('backups.upload.file')}>
        {(p) => (
          <Input
            type="file"
            accept=".db,application/octet-stream"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            {...p}
          />
        )}
      </Field>
      {missing && <Alert>{t('backups.upload.choose')}</Alert>}
      {upload.isError && <Alert>{errorMessage(upload.error)}</Alert>}
      <Button type="submit" variant="secondary" disabled={upload.isPending}>
        {t('backups.upload.send')}
      </Button>
    </form>
  )
}

function RestoreDialog({ name, onClose }: { name: string | null; onClose: () => void }) {
  const { t } = useTranslation()
  const [word, setWord] = useState('')
  const start = useMutation({
    mutationFn: (file: string) =>
      unwrap(api.POST('/api/v1/system/restore', { body: { name: file, confirm: word } })),
  })

  function close() {
    setWord('')
    start.reset()
    onClose()
  }

  return (
    <Dialog open={name !== null} onClose={close} title={t('backups.restoreTitle')}>
      {name !== null && !start.isSuccess && (
        <form
          className="space-y-4"
          aria-label={t('backups.restoreTitle')}
          onSubmit={(e) => {
            e.preventDefault()
            start.mutate(name)
          }}
        >
          <p>
            {t('backups.restoreWhat')} <strong>{name}</strong>
          </p>
          <ul className="list-disc space-y-1 pl-5 text-sm">
            <li>{t('backups.warn.replace')}</li>
            <li>{t('backups.warn.kept')}</li>
            <li>{t('backups.warn.restart')}</li>
            <li>{t('backups.warn.signedOut')}</li>
            <li>{t('backups.warn.keys')}</li>
          </ul>
          <Field label={t('backups.typeWord')}>
            {(p) => <Input value={word} onChange={(e) => setWord(e.target.value)} {...p} />}
          </Field>
          {start.isError && <Alert>{errorMessage(start.error)}</Alert>}
          <Button type="submit" disabled={word !== 'RESTORE' || start.isPending}>
            {t('backups.restoreNow')}
          </Button>
        </form>
      )}
      {start.isSuccess && (
        <p role="status" className="space-y-2">
          {start.data.note}
        </p>
      )}
    </Dialog>
  )
}
