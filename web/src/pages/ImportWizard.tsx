import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { api, errorMessage, unwrap } from '../api/client'
import {
  useAccounts,
  useInvalidateLedger,
  type DryRun,
  type ImportBatch,
  type ImportMapping,
  type ImportPreview,
} from '../api/queries'
import { Badge } from '../components/display'
import { TYPES } from '../components/TransactionForm'
import { Alert, Button, Checkbox, Field, Input, Select } from '../components/ui'
import { cn } from '../lib/cn'

type Step = 'upload' | 'map' | 'review' | 'done'

const COLUMN_FIELDS = [
  'date_col',
  'time_col',
  'isin_col',
  'type_col',
  'quantity_col',
  'price_col',
  'currency_col',
  'fx_col',
  'fees_col',
  'fees_currency_col',
  'amount_col',
  'reference_col',
  'note_col',
] as const
type ColumnField = (typeof COLUMN_FIELDS)[number]

const DATE_FORMATS = [
  ['%d-%m-%Y', 'DD-MM-YYYY'],
  ['%Y-%m-%d', 'YYYY-MM-DD'],
  ['%d/%m/%Y', 'DD/MM/YYYY'],
  ['%d.%m.%Y', 'DD.MM.YYYY'],
  ['%m/%d/%Y', 'MM/DD/YYYY'],
  ['%d-%m-%y', 'DD-MM-YY'],
] as const

const STEPS = ['upload', 'map', 'review'] as const

function usePresets() {
  return useQuery({
    queryKey: ['import-presets'],
    queryFn: () => unwrap(api.GET('/api/v1/import-presets')),
  })
}

export function ImportWizard() {
  const { t } = useTranslation()
  const [step, setStep] = useState<Step>('upload')
  const [preview, setPreview] = useState<ImportPreview | null>(null)
  const [mapping, setMapping] = useState<ImportMapping | null>(null)
  const [dry, setDry] = useState<DryRun | null>(null)
  const [done, setDone] = useState<ImportBatch | null>(null)

  const current = step === 'done' ? 'review' : step
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-semibold">{t('import.title')}</h1>
        <Link to="/transactions" className="text-sm underline">
          {t('import.back')}
        </Link>
      </div>
      <ol className="flex gap-2 text-sm" aria-label={t('import.title')}>
        {STEPS.map((s, i) => (
          <li
            key={s}
            aria-current={current === s ? 'step' : undefined}
            className={cn(
              'rounded-md border px-3 py-1',
              current === s ? 'border-primary font-medium' : 'border-border text-muted',
            )}
          >
            {i + 1}. {t(`import.steps.${s}`)}
          </li>
        ))}
      </ol>

      {step === 'upload' && (
        <UploadStep
          onUploaded={(p) => {
            setPreview(p)
            setMapping(p.mapping)
            setDry(null)
            setStep('map')
          }}
        />
      )}
      {step === 'map' && preview && mapping && (
        <MapStep
          preview={preview}
          mapping={mapping}
          onChange={setMapping}
          onChecked={(result) => {
            setDry(result)
            setStep('review')
          }}
        />
      )}
      {step === 'review' && preview && mapping && dry && (
        <ReviewStep
          mapping={mapping}
          dry={dry}
          onDry={setDry}
          onBack={() => setStep('map')}
          onDone={(batch) => {
            setDone(batch)
            setStep('done')
          }}
        />
      )}
      {step === 'done' && done && <DoneStep batch={done} onUndone={() => setStep('upload')} />}

      {step === 'upload' && <ImportHistory />}
    </div>
  )
}

function UploadStep({ onUploaded }: { onUploaded: (p: ImportPreview) => void }) {
  const { t } = useTranslation()
  const accounts = useAccounts()
  const presets = usePresets()
  const [accountId, setAccountId] = useState('')
  const [presetId, setPresetId] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [missing, setMissing] = useState(false)
  const account = accountId || (accounts.data?.[0] ? String(accounts.data[0].id) : '')

  const upload = useMutation({
    mutationFn: () => {
      const form = new FormData()
      form.set('account_id', account)
      if (presetId) form.set('preset_id', presetId)
      form.set('file', file as File)
      return unwrap(
        api.POST('/api/v1/imports', {
          body: {} as never,
          bodySerializer: () => form,
        }),
      )
    },
    onSuccess: onUploaded,
  })

  return (
    <form
      className="max-w-xl space-y-4"
      onSubmit={(e) => {
        e.preventDefault()
        if (!file) return setMissing(true)
        setMissing(false)
        upload.mutate()
      }}
    >
      {accounts.data?.length === 0 && <Alert>{t('transactions.noAccounts')}</Alert>}
      <Field label={t('import.upload.account')}>
        {(p) => (
          <Select value={account} onChange={(e) => setAccountId(e.target.value)} {...p}>
            {accounts.data?.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </Select>
        )}
      </Field>
      <Field label={t('import.upload.preset')}>
        {(p) => (
          <Select value={presetId} onChange={(e) => setPresetId(e.target.value)} {...p}>
            <option value="">{t('import.upload.noPreset')}</option>
            {presets.data?.map((x) => (
              <option key={x.id} value={x.id}>
                {x.name}
              </option>
            ))}
          </Select>
        )}
      </Field>
      <Field
        label={t('import.upload.file')}
        hint={t('import.upload.fileHint')}
        error={missing ? t('import.upload.choose') : undefined}
      >
        {(p) => (
          <Input
            type="file"
            accept=".csv,text/csv,text/plain"
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null)
              setMissing(false)
            }}
            {...p}
          />
        )}
      </Field>
      {upload.isError && <Alert>{errorMessage(upload.error)}</Alert>}
      <Button type="submit" disabled={upload.isPending || !account}>
        {t('import.upload.submit')}
      </Button>
    </form>
  )
}

function MapStep({
  preview,
  mapping,
  onChange,
  onChecked,
}: {
  preview: ImportPreview
  mapping: ImportMapping
  onChange: (m: ImportMapping) => void
  onChecked: (d: DryRun) => void
}) {
  const { t } = useTranslation()
  const patch = (changes: Partial<ImportMapping>) => onChange({ ...mapping, ...changes })
  const typeRows = Object.entries(mapping.type_map ?? {})

  const check = useMutation({
    mutationFn: () =>
      unwrap(
        api.PUT('/api/v1/imports/{batch_id}/mapping', {
          params: { path: { batch_id: preview.batch.id } },
          body: { mapping },
        }),
      ),
    onSuccess: onChecked,
  })

  function setTypeRow(index: number, key: string, value: string) {
    const next = typeRows.map(([k, v], i) => (i === index ? [key, value] : [k, v]))
    patch({ type_map: Object.fromEntries(next) })
  }

  return (
    <form
      className="space-y-5"
      onSubmit={(e) => {
        e.preventDefault()
        check.mutate()
      }}
    >
      {preview.detected_preset && (
        <p role="status" className="font-medium">
          {t(`import.map.recognised.${preview.detected_preset}`, {
            defaultValue: t('import.map.recognisedOther'),
          })}
        </p>
      )}
      <p>
        {t('import.map.intro', {
          count: preview.row_count,
          encoding: preview.encoding,
          delimiter: preview.delimiter === '\t' ? 'tab' : preview.delimiter,
        })}
      </p>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <caption className="pb-1 text-left text-sm font-medium">{t('import.map.sample')}</caption>
          <thead>
            <tr className="border-b border-border">
              {preview.headers.map((h, i) => (
                <th key={i} scope="col" className="px-2 py-1 text-left font-medium">
                  {h.label || `(${i + 1})`}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {preview.sample_rows.map((row, r) => (
              <tr key={r} className="border-b border-border">
                {row.map((cell, c) => (
                  <td key={c} className="px-2 py-1 whitespace-nowrap">
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {COLUMN_FIELDS.map((field: ColumnField) => (
          <Field key={field} label={t(`import.map.fields.${field}`)}>
            {(p) => (
              <Select
                value={mapping[field] ?? ''}
                onChange={(e) =>
                  patch({ [field]: e.target.value === '' ? null : Number(e.target.value) })
                }
                {...p}
              >
                <option value="">{t('import.map.none')}</option>
                {preview.headers.map((h, i) => (
                  <option key={i} value={i}>
                    {h.label || `(${i + 1})`}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        ))}
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Field label={t('import.map.dateFormat')}>
          {(p) => (
            <Select
              value={mapping.date_format}
              onChange={(e) => patch({ date_format: e.target.value })}
              {...p}
            >
              {!DATE_FORMATS.some(([f]) => f === mapping.date_format) && (
                <option value={mapping.date_format}>{mapping.date_format}</option>
              )}
              {DATE_FORMATS.map(([format, label]) => (
                <option key={format} value={format}>
                  {label}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label={t('import.map.decimal')}>
          {(p) => (
            <Select
              value={mapping.decimal_separator}
              onChange={(e) =>
                patch({ decimal_separator: e.target.value as ImportMapping['decimal_separator'] })
              }
              {...p}
            >
              <option value=".">1234.56</option>
              <option value=",">1234,56</option>
            </Select>
          )}
        </Field>
        <Field label={t('import.map.thousands')}>
          {(p) => (
            <Select
              value={mapping.thousands_separator}
              onChange={(e) =>
                patch({
                  thousands_separator: e.target.value as ImportMapping['thousands_separator'],
                })
              }
              {...p}
            >
              <option value="">{t('import.map.thousandsNone')}</option>
              <option value=",">1,234.56</option>
              <option value=".">1.234,56</option>
              <option value=" ">{t('import.map.thousandsSpace')}</option>
            </Select>
          )}
        </Field>
        <Field label={t('import.map.typeMode')}>
          {(p) => (
            <Select
              value={mapping.type_mode}
              onChange={(e) => patch({ type_mode: e.target.value as ImportMapping['type_mode'] })}
              {...p}
            >
              <option value="sign">{t('import.map.typeSign')}</option>
              <option value="column">{t('import.map.typeColumn')}</option>
            </Select>
          )}
        </Field>
        <Field label={t('import.map.defaultCurrency')}>
          {(p) => (
            <Input
              value={mapping.default_currency ?? ''}
              maxLength={3}
              onChange={(e) => patch({ default_currency: e.target.value.toUpperCase() || null })}
              {...p}
            />
          )}
        </Field>
        <Field label={t('import.map.fxSemantics')}>
          {(p) => (
            <Select
              value={mapping.fx_semantics}
              onChange={(e) =>
                patch({ fx_semantics: e.target.value as ImportMapping['fx_semantics'] })
              }
              {...p}
            >
              <option value="per_eur">{t('import.map.fxPerEur')}</option>
              <option value="to_eur">{t('import.map.fxToEur')}</option>
            </Select>
          )}
        </Field>
        <div className="sm:col-span-2 lg:col-span-3">
          <Field label={t('import.map.skip')}>
            {(p) => (
              <Input
                value={(mapping.skip_types ?? []).join(', ')}
                onChange={(e) =>
                  patch({
                    skip_types: e.target.value
                      .split(',')
                      .map((s) => s.trim())
                      .filter(Boolean),
                  })
                }
                {...p}
              />
            )}
          </Field>
        </div>
      </div>

      <fieldset className="space-y-1">
        <legend className="font-medium">{t('import.map.extraFees')}</legend>
        <p className="text-sm text-muted">{t('import.map.extraFeesHint')}</p>
        <div className="flex flex-wrap gap-x-6">
          {preview.headers.map((h, i) => (
            <Checkbox
              key={i}
              label={h.label || `(${i + 1})`}
              checked={(mapping.extra_fee_cols ?? []).includes(i)}
              onChange={(e) =>
                patch({
                  extra_fee_cols: e.target.checked
                    ? [...(mapping.extra_fee_cols ?? []), i].sort((a, b) => a - b)
                    : (mapping.extra_fee_cols ?? []).filter((c) => c !== i),
                })
              }
            />
          ))}
        </div>
      </fieldset>

      {mapping.type_mode === 'column' && (
        <fieldset className="space-y-2">
          <legend className="font-medium">{t('import.map.typeMap')}</legend>
          <p className="text-sm text-muted">{t('import.map.typeMapHint')}</p>
          {typeRows.map(([text, type], i) => (
            <div key={i} className="grid gap-2 sm:grid-cols-2">
              <Field label={t('import.map.typeText')}>
                {(p) => (
                  <Input
                    value={text}
                    onChange={(e) => setTypeRow(i, e.target.value, type)}
                    {...p}
                  />
                )}
              </Field>
              <Field label={t('transactions.columns.type')}>
                {(p) => (
                  <Select value={type} onChange={(e) => setTypeRow(i, text, e.target.value)} {...p}>
                    {TYPES.map((x) => (
                      <option key={x} value={x}>
                        {t(`transactions.types.${x}`)}
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
            </div>
          ))}
          <Button
            variant="secondary"
            onClick={() =>
              patch({
                type_map: { ...(mapping.type_map ?? {}), [`value ${typeRows.length + 1}`]: 'buy' },
              })
            }
          >
            {t('import.map.addType')}
          </Button>
        </fieldset>
      )}

      {check.isError && <Alert>{errorMessage(check.error)}</Alert>}
      <Button type="submit" disabled={check.isPending}>
        {t(check.isPending ? 'import.map.checking' : 'import.map.check')}
      </Button>
    </form>
  )
}

function ReviewStep({
  mapping,
  dry,
  onDry,
  onBack,
  onDone,
}: {
  mapping: ImportMapping
  dry: DryRun
  onDry: (next: DryRun) => void
  onBack: () => void
  onDone: (b: ImportBatch) => void
}) {
  const { t } = useTranslation()
  const invalidate = useInvalidateLedger()
  const [onlyProblems, setOnlyProblems] = useState(false)
  const [skipErrors, setSkipErrors] = useState(false)
  const [presetName, setPresetName] = useState('')
  const [added, setAdded] = useState<AddedInstrument[]>([])
  const counts = { new: 0, duplicate: 0, error: 0, skipped: 0, ...dry.counts }
  const rows = onlyProblems ? dry.rows.filter((r) => r.status === 'error') : dry.rows
  const canCommit = counts.new > 0 && (counts.error === 0 || skipErrors)

  const commit = useMutation({
    mutationFn: async () => {
      if (presetName.trim()) {
        await unwrap(
          api.POST('/api/v1/import-presets', { body: { name: presetName.trim(), mapping } }),
        )
      }
      return unwrap(
        api.POST('/api/v1/imports/{batch_id}/commit', {
          params: { path: { batch_id: dry.batch_id } },
          body: { skip_errors: skipErrors },
        }),
      )
    },
    onSuccess: async (batch) => {
      await invalidate()
      onDone(batch)
    },
  })

  return (
    <div className="space-y-4">
      <p role="status" className="font-medium">
        {t('import.review.counts', counts)}
      </p>
      {dry.missing.length > 0 && (
        <MissingInstruments dry={dry} onDry={onDry} onResults={setAdded} />
      )}
      {added.length > 0 && (
        <ul className="space-y-1 text-sm" aria-label={t('import.missing.results')}>
          {added.map((r) => (
            <li key={r.isin} className={r.status === 'failed' ? 'text-danger' : ''}>
              {t(`import.missing.status.${r.status}`, {
                name: r.name,
                isin: r.isin,
                detail: r.detail,
              })}
            </li>
          ))}
        </ul>
      )}
      {counts.new === 0 && counts.error === 0 && <p>{t('import.review.nothing')}</p>}

      <Checkbox
        label={t('import.review.onlyProblems')}
        checked={onlyProblems}
        onChange={(e) => setOnlyProblems(e.target.checked)}
      />
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <caption className="sr-only">{t('import.review.caption')}</caption>
          <thead>
            <tr className="border-b border-border text-left">
              {(['row', 'status', 'date', 'type', 'isin', 'units', 'price', 'reason'] as const).map(
                (c) => (
                  <th key={c} scope="col" className="py-1 pr-3 font-medium">
                    {t(`import.review.columns.${c}`)}
                  </th>
                ),
              )}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.row} className="border-b border-border align-top">
                <td className="py-1 pr-3 tabular-nums">{r.row}</td>
                <td className="py-1 pr-3">
                  <Badge
                    tone={r.status === 'new' ? 'good' : r.status === 'error' ? 'bad' : 'neutral'}
                  >
                    {t(`import.review.status.${r.status}`, { defaultValue: r.status })}
                  </Badge>
                </td>
                <td className="py-1 pr-3 whitespace-nowrap">{r.summary?.date ?? ''}</td>
                <td className="py-1 pr-3">
                  {r.summary?.type
                    ? t(`transactions.types.${r.summary.type}`, { defaultValue: r.summary.type })
                    : ''}
                </td>
                <td className="py-1 pr-3">{r.summary?.isin ?? ''}</td>
                <td className="py-1 pr-3 text-right tabular-nums">{r.summary?.quantity ?? ''}</td>
                <td className="py-1 pr-3 text-right tabular-nums">{r.summary?.price ?? ''}</td>
                <td className="py-1 text-danger">{r.reason ?? ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {dry.truncated && <p className="pt-2 text-sm text-muted">{t('import.review.truncated')}</p>}
      </div>

      {counts.error > 0 && (
        <Checkbox
          label={t('import.review.validOnly')}
          checked={skipErrors}
          onChange={(e) => setSkipErrors(e.target.checked)}
        />
      )}
      <div className="max-w-sm">
        <Field label={t('import.review.savePreset')}>
          {(p) => (
            <Input
              value={presetName}
              placeholder={t('import.review.presetName')}
              onChange={(e) => setPresetName(e.target.value)}
              {...p}
            />
          )}
        </Field>
      </div>

      {commit.isError && <Alert>{errorMessage(commit.error)}</Alert>}
      <div className="flex gap-2">
        <Button variant="secondary" onClick={onBack}>
          {t('import.review.backToMap')}
        </Button>
        <Button disabled={!canCommit || commit.isPending} onClick={() => commit.mutate()}>
          {t('import.review.commit', { count: counts.new })}
        </Button>
      </div>
    </div>
  )
}

function DoneStep({ batch, onUndone }: { batch: ImportBatch; onUndone: () => void }) {
  const { t } = useTranslation()
  const invalidate = useInvalidateLedger()
  const undo = useMutation({
    mutationFn: () =>
      unwrap(
        api.DELETE('/api/v1/imports/{batch_id}', { params: { path: { batch_id: batch.id } } }),
      ),
    onSuccess: async () => {
      await invalidate()
      onUndone()
    },
  })
  return (
    <div className="space-y-4">
      <p role="status" className="font-medium">
        {t('import.review.done', { imported: batch.rows_imported, skipped: batch.rows_skipped })}
      </p>
      {undo.isError && <Alert>{errorMessage(undo.error)}</Alert>}
      <div className="flex gap-2">
        <Link
          to="/transactions"
          className="inline-flex min-h-10 items-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground"
        >
          {t('import.review.viewTransactions')}
        </Link>
        <Button variant="secondary" onClick={() => undo.mutate()} disabled={undo.isPending}>
          {t('import.review.undo')}
        </Button>
      </div>
    </div>
  )
}

function ImportHistory() {
  const { t } = useTranslation()
  const invalidate = useInvalidateLedger()
  const list = useQuery({
    queryKey: ['imports'],
    queryFn: () => unwrap(api.GET('/api/v1/imports')),
  })
  const undo = useMutation({
    mutationFn: (b: ImportBatch) =>
      unwrap(api.DELETE('/api/v1/imports/{batch_id}', { params: { path: { batch_id: b.id } } })),
    onSuccess: async () => {
      await invalidate()
      await list.refetch()
    },
  })
  const rows = list.data ?? []
  return (
    <section className="space-y-2 pt-4">
      <h2 className="text-lg font-semibold">{t('import.history.title')}</h2>
      {undo.isError && <Alert>{errorMessage(undo.error)}</Alert>}
      {list.isSuccess && rows.length === 0 ? (
        <p className="text-muted">{t('import.history.empty')}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <caption className="sr-only">{t('import.history.caption')}</caption>
            <thead>
              <tr className="border-b border-border text-left">
                {(['file', 'when', 'status', 'rows', 'actions'] as const).map((c) => (
                  <th key={c} scope="col" className="py-1 pr-3 font-medium">
                    {t(`import.history.columns.${c}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((b) => (
                <tr key={b.id} className="border-b border-border">
                  <td className="py-1 pr-3">{b.file_name}</td>
                  <td className="py-1 pr-3 whitespace-nowrap">
                    {b.created_at.slice(0, 16).replace('T', ' ')}
                  </td>
                  <td className="py-1 pr-3">
                    {t(`import.history.status.${b.status}`, { defaultValue: b.status })}
                  </td>
                  <td className="py-1 pr-3">
                    {b.status === 'committed'
                      ? t('import.history.rows', {
                          imported: b.rows_imported,
                          skipped: b.rows_skipped,
                        })
                      : ''}
                  </td>
                  <td className="py-1">
                    {b.status !== 'undone' && (
                      <Button
                        variant="ghost"
                        onClick={() => {
                          if (
                            b.status === 'preview' ||
                            window.confirm(t('import.history.undoConfirm', { file: b.file_name }))
                          )
                            undo.mutate(b)
                        }}
                      >
                        {t(
                          b.status === 'preview' ? 'import.history.discard' : 'import.history.undo',
                        )}
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

/** The file names instruments Folio does not know yet (always so on a first import): add them
 * here, looked up by ISIN on the exchange the file names, or by hand (FR-TX-07). */
type AddedInstrument = { isin: string; name: string; status: string; detail: string }

function MissingInstruments({
  dry,
  onDry,
  onResults,
}: {
  dry: DryRun
  onDry: (next: DryRun) => void
  onResults: (results: AddedInstrument[]) => void
}) {
  const { t } = useTranslation()
  const invalidate = useInvalidateLedger()
  const add = useMutation({
    mutationFn: (byHand: boolean) =>
      unwrap(
        api.POST('/api/v1/imports/{batch_id}/instruments', {
          params: { path: { batch_id: dry.batch_id } },
          body: { by_hand: byHand },
        }),
      ),
    onSuccess: async (result) => {
      await invalidate()
      onResults(result.results)
      onDry(result.dry_run)
    },
  })
  return (
    <section
      aria-labelledby="missing-title"
      className="space-y-3 rounded-md border border-border p-3"
    >
      <h3 id="missing-title" className="font-medium">
        {t('import.missing.title', { count: dry.missing.length })}
      </h3>
      <p className="text-sm text-muted">{t('import.missing.intro')}</p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <caption className="sr-only">
            {t('import.missing.title', { count: dry.missing.length })}
          </caption>
          <thead>
            <tr className="border-b border-border text-left">
              {(['isin', 'name', 'exchange', 'currency', 'rows'] as const).map((c) => (
                <th key={c} scope="col" className="py-1 pr-3 font-medium">
                  {t(`import.missing.columns.${c}`)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {dry.missing.map((m) => (
              <tr key={m.isin} className="border-b border-border">
                <td className="py-1 pr-3 font-mono text-xs">{m.isin}</td>
                <td className="py-1 pr-3">{m.name || '–'}</td>
                <td className="py-1 pr-3">{m.exchange ?? '–'}</td>
                <td className="py-1 pr-3">{m.currency ?? '–'}</td>
                <td className="py-1 pr-3 tabular-nums">{m.rows}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button onClick={() => add.mutate(false)} disabled={add.isPending}>
          {t('import.missing.lookUp')}
        </Button>
        <Button variant="secondary" onClick={() => add.mutate(true)} disabled={add.isPending}>
          {t('import.missing.byHand')}
        </Button>
        {add.isPending && (
          <span role="status" className="text-sm text-muted">
            {t('import.missing.working')}
          </span>
        )}
      </div>
      {add.isError && <Alert>{errorMessage(add.error)}</Alert>}
    </section>
  )
}
