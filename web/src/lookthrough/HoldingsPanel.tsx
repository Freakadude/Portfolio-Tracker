import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../api/client'
import { Badge } from '../components/display'
import { Alert, Button, Checkbox, Field, Help, Input, Select } from '../components/ui'
import {
  useDeleteSnapshot,
  useHoldings,
  usePreviewHoldings,
  useRefreshHoldings,
  useSaveSource,
  useStoreHoldings,
  type HoldingsMapping,
  type HoldingsPreview,
} from './api'

const COLUMNS = ['name', 'weight', 'isin', 'ticker', 'sector', 'country', 'currency'] as const

/** On an ETF's page: its saved holdings, a way to add a file (previewed first, with the column
 * match changeable), and where Folio refreshes it from each month (FR-MD-09). */
export function HoldingsPanel({ instrumentId }: { instrumentId: number }) {
  const { t } = useTranslation()
  const holdings = useHoldings(instrumentId)
  const remove = useDeleteSnapshot(instrumentId)
  const view = holdings.data
  return (
    <section aria-labelledby="holdings-h" className="space-y-4">
      <div>
        <h2 id="holdings-h" className="text-lg font-semibold">
          {t('etfHoldings.title')}
        </h2>
        <p className="text-sm text-muted">{t('etfHoldings.intro')}</p>
        <Help title={t('etfHoldings.helpTitle')}>
          <p>{t('etfHoldings.help1')}</p>
          <p>{t('etfHoldings.help2')}</p>
          <p>{t('etfHoldings.help3')}</p>
        </Help>
      </div>
      {holdings.isError && <Alert>{errorMessage(holdings.error)}</Alert>}
      {remove.isError && <Alert>{errorMessage(remove.error)}</Alert>}
      {view && view.snapshots.length === 0 && (
        <p className="text-sm text-muted">{t('etfHoldings.empty')}</p>
      )}
      {view && view.snapshots.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <caption className="mb-1 text-left font-medium">{t('etfHoldings.snapshots')}</caption>
            <thead>
              <tr className="border-b border-border text-left">
                {(['date', 'source', 'holdings', 'covered', 'actions'] as const).map((c) => (
                  <th key={c} scope="col" className="py-1 pr-3 font-medium">
                    {t(`etfHoldings.columns.${c}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {view.snapshots.map((s) => (
                <tr key={s.id} className="border-b border-border">
                  <td className="py-1 pr-3 whitespace-nowrap">
                    {s.as_of} {s.stale && <Badge tone="warn">{t('etfHoldings.stale')}</Badge>}
                  </td>
                  <td className="py-1 pr-3">{t(`etfHoldings.sources.${s.source}`)}</td>
                  <td className="py-1 pr-3 tabular-nums">{s.holdings}</td>
                  <td className="py-1 pr-3 tabular-nums">
                    {t('etfHoldings.coveredPct', { pct: Number(s.covered_pct).toFixed(1) })}
                  </td>
                  <td className="py-1">
                    <Button
                      variant="secondary"
                      onClick={() => {
                        if (window.confirm(t('etfHoldings.deleteConfirm', { date: s.as_of })))
                          remove.mutate(s.id)
                      }}
                      aria-label={`${t('etfHoldings.delete')} ${s.as_of}`}
                    >
                      {t('etfHoldings.delete')}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {view && view.top.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <caption className="mb-1 text-left font-medium">{t('etfHoldings.top')}</caption>
            <thead>
              <tr className="border-b border-border text-left">
                {(['name', 'weight', 'sector', 'country'] as const).map((c) => (
                  <th key={c} scope="col" className="py-1 pr-3 font-medium">
                    {t(`etfHoldings.topColumns.${c}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {view.top.slice(0, 10).map((c) => (
                <tr key={`${c.name}-${c.isin}`} className="border-b border-border">
                  <td className="py-1 pr-3">{c.name}</td>
                  <td className="py-1 pr-3 tabular-nums">{Number(c.weight_pct).toFixed(2)}</td>
                  <td className="py-1 pr-3">{c.sector ?? '–'}</td>
                  <td className="py-1 pr-3">{c.country ?? '–'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Upload instrumentId={instrumentId} />
      {view && (
        <Source instrumentId={instrumentId} url={view.source.url ?? ''} eodhd={view.source.eodhd} />
      )}
    </section>
  )
}

function Upload({ instrumentId }: { instrumentId: number }) {
  const { t } = useTranslation()
  const preview = usePreviewHoldings(instrumentId)
  const store = useStoreHoldings(instrumentId)
  const [file, setFile] = useState<File | null>(null)
  const [missing, setMissing] = useState(false)
  const [mapping, setMapping] = useState<HoldingsMapping | undefined>()
  const [asOf, setAsOf] = useState('')
  const shown: HoldingsPreview | undefined = preview.data

  function read(next?: HoldingsMapping, sheet?: string) {
    if (!file) return setMissing(true)
    setMissing(false)
    preview.mutate(
      { file, mapping: next, sheet },
      { onSuccess: (p) => setMapping(next ?? p.mapping) },
    )
  }

  const change = (key: (typeof COLUMNS)[number], value: string) =>
    setMapping((m) => (m ? { ...m, [key]: value === '' ? null : Number(value) } : m))

  return (
    <div className="space-y-3 rounded-md border border-border p-4">
      <h3 className="font-medium">{t('etfHoldings.upload.title')}</h3>
      <Field label={t('etfHoldings.upload.file')}>
        {(p) => (
          <Input
            type="file"
            accept=".csv,.xlsx,.pdf,text/csv,text/plain,application/pdf,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null)
              setMapping(undefined)
              preview.reset()
              store.reset()
            }}
            {...p}
          />
        )}
      </Field>
      {missing && <Alert>{t('etfHoldings.upload.choose')}</Alert>}
      <Button variant="secondary" onClick={() => read()} disabled={preview.isPending}>
        {t('etfHoldings.upload.preview')}
      </Button>
      {preview.isError && <Alert>{errorMessage(preview.error)}</Alert>}
      {shown && (
        <div className="space-y-3">
          <p className="text-sm" role="status">
            {t('etfHoldings.upload.readAs', {
              count: shown.holdings,
              pct: Number(shown.covered_pct).toFixed(1),
              date: shown.as_of ?? t('etfHoldings.upload.noDate'),
            })}
          </p>
          {shown.errors.map((e) => (
            <Alert key={e}>{e}</Alert>
          ))}
          {shown.warnings.map((w) => (
            <p key={w} className="text-sm text-muted">
              {w}
            </p>
          ))}
          {shown.dropped.length > 0 && (
            <p className="text-sm text-muted">
              {t('etfHoldings.upload.dropped', { lines: shown.dropped.join('; ') })}
            </p>
          )}
          {shown.sheets.length > 1 && (
            <Field label={t('etfHoldings.upload.sheet')} hint={t('etfHoldings.upload.sheetHint')}>
              {(p) => (
                <Select
                  value={mapping?.sheet ?? ''}
                  onChange={(e) => read(undefined, e.target.value)}
                  {...p}
                >
                  {shown.sheets.map((s) => (
                    <option key={s.name} value={s.name}>
                      {t('etfHoldings.upload.sheetOption', { name: s.name, count: s.holdings })}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
          )}
          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">{t('etfHoldings.upload.mapping')}</legend>
            <p className="text-xs text-muted">{t('etfHoldings.upload.mappingHint')}</p>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {COLUMNS.map((c) => (
                <Field key={c} label={t(`etfHoldings.upload.columns.${c}`)}>
                  {(p) => (
                    <Select
                      value={
                        mapping?.[c] === null || mapping?.[c] === undefined
                          ? ''
                          : String(mapping[c])
                      }
                      onChange={(e) => change(c, e.target.value)}
                      {...p}
                    >
                      <option value="">{t('etfHoldings.upload.none')}</option>
                      {shown.headers.map((h) => (
                        <option key={h.index} value={h.index}>
                          {h.label}
                        </option>
                      ))}
                    </Select>
                  )}
                </Field>
              ))}
            </div>
            <Button variant="secondary" onClick={() => read(mapping)} disabled={preview.isPending}>
              {t('etfHoldings.upload.reread')}
            </Button>
          </fieldset>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left">
                  {(['name', 'weight', 'sector', 'country'] as const).map((c) => (
                    <th key={c} scope="col" className="py-1 pr-3 font-medium">
                      {t(`etfHoldings.topColumns.${c}`)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {shown.top.slice(0, 8).map((c) => (
                  <tr key={`${c.name}-${c.isin}`} className="border-b border-border">
                    <td className="py-1 pr-3">{c.name}</td>
                    <td className="py-1 pr-3 tabular-nums">{Number(c.weight_pct).toFixed(2)}</td>
                    <td className="py-1 pr-3">{c.sector ?? '–'}</td>
                    <td className="py-1 pr-3">{c.country ?? '–'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Field label={t('etfHoldings.upload.date')} hint={t('etfHoldings.upload.dateHint')}>
            {(p) => (
              <Input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} {...p} />
            )}
          </Field>
          <Button
            onClick={() => file && store.mutate({ file, mapping, asOf: asOf || undefined })}
            disabled={store.isPending || shown.errors.length > 0}
          >
            {t('etfHoldings.upload.store')}
          </Button>
          {store.isError && <Alert>{errorMessage(store.error)}</Alert>}
          {store.isSuccess && (
            <p role="status" className="text-sm text-gain">
              {t('etfHoldings.upload.stored', {
                count: store.data.snapshot.holdings,
                date: store.data.snapshot.as_of,
              })}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

function Source({
  instrumentId,
  url: savedUrl,
  eodhd: savedEodhd,
}: {
  instrumentId: number
  url: string
  eodhd: boolean
}) {
  const { t } = useTranslation()
  const save = useSaveSource(instrumentId)
  const refresh = useRefreshHoldings(instrumentId)
  const [url, setUrl] = useState(savedUrl)
  const [eodhd, setEodhd] = useState(savedEodhd)
  return (
    <form
      className="space-y-3 rounded-md border border-border p-4"
      onSubmit={(e) => {
        e.preventDefault()
        save.mutate({ url: url.trim() || null, eodhd })
      }}
    >
      <h3 className="font-medium">{t('etfHoldings.source.title')}</h3>
      <p className="text-sm text-muted">{t('etfHoldings.source.intro')}</p>
      <Field label={t('etfHoldings.source.url')}>
        {(p) => <Input value={url} onChange={(e) => setUrl(e.target.value)} {...p} />}
      </Field>
      <Checkbox
        label={t('etfHoldings.source.eodhd')}
        checked={eodhd}
        onChange={(e) => setEodhd(e.target.checked)}
      />
      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" disabled={save.isPending}>
          {t('etfHoldings.source.save')}
        </Button>
        <Button
          variant="secondary"
          onClick={() => refresh.mutate()}
          disabled={refresh.isPending || (!savedUrl && !savedEodhd)}
        >
          {t('etfHoldings.source.refresh')}
        </Button>
        {save.isSuccess && (
          <span role="status" className="text-sm text-gain">
            {t('etfHoldings.source.saved')}
          </span>
        )}
        {refresh.isSuccess && (
          <span role="status" className="text-sm">
            {t('etfHoldings.source.queued')}
          </span>
        )}
      </div>
      {save.isError && <Alert>{errorMessage(save.error)}</Alert>}
      {refresh.isError && <Alert>{errorMessage(refresh.error)}</Alert>}
    </form>
  )
}
