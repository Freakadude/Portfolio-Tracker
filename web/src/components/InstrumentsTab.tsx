import { useMutation } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { ApiProblem, api, errorMessage, unwrap } from '../api/client'
import { useInstruments, useInvalidateLedger, type Instrument } from '../api/queries'
import { useFormat } from '../lib/useFormat'
import { ASSET_CLASSES } from './AddInstrumentDialog'
import { AsOf, Badge, Dialog, EmptyState } from './display'
import { useSleeves } from '../dashboards/api'
import { Alert, Button, Checkbox, Field, Input, Select } from './ui'

type Filter = 'active' | 'archived' | 'all'
type Blocked = { name: string; total: number; rows: Record<string, string>[] }

export function InstrumentsTab({ onAdd }: { onAdd: () => void }) {
  const { t } = useTranslation()
  const { eur } = useFormat()
  const invalidate = useInvalidateLedger()
  const [filter, setFilter] = useState<Filter>('active')
  const [editing, setEditing] = useState<Instrument | null>(null)
  const [pricing, setPricing] = useState<Instrument | null>(null)
  const [blocked, setBlocked] = useState<Blocked | null>(null)
  const { data, isPending, isError, error } = useInstruments(filter)

  const archive = useMutation({
    mutationFn: (i: Instrument) =>
      unwrap(
        api.PATCH('/api/v1/instruments/{instrument_id}', {
          params: { path: { instrument_id: i.id } },
          body: { status: i.status === 'active' ? 'archived' : 'active' },
        }),
      ),
    onSuccess: invalidate,
  })
  const remove = useMutation({
    mutationFn: (i: Instrument) =>
      unwrap(
        api.DELETE('/api/v1/instruments/{instrument_id}', {
          params: { path: { instrument_id: i.id } },
        }),
      ),
    onSuccess: invalidate,
    onError: (err, i) => {
      if (err instanceof ApiProblem && err.status === 409) {
        setBlocked({
          name: i.name,
          total: Number(err.extra.blocking_total ?? 0),
          rows: (err.extra.blocking_transactions as Record<string, string>[]) ?? [],
        })
      }
    },
  })

  if (isPending) return <p role="status">{t('app.loading')}</p>
  if (isError) return <Alert>{errorMessage(error)}</Alert>

  return (
    <div className="space-y-4">
      <div
        className="flex flex-wrap items-center gap-2"
        role="group"
        aria-label={t('instruments.title')}
      >
        {(['active', 'archived', 'all'] as const).map((f) => (
          <Button
            key={f}
            variant={filter === f ? 'primary' : 'secondary'}
            onClick={() => setFilter(f)}
          >
            {t(`instruments.filters.${f}`)}
          </Button>
        ))}
      </div>

      {data.length === 0 ? (
        <EmptyState
          title={t('instruments.empty.title')}
          body={t('instruments.empty.body')}
          action={<Button onClick={onAdd}>{t('holdings.add')}</Button>}
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[56rem] border-collapse text-sm">
            <caption className="sr-only">{t('instruments.caption')}</caption>
            <thead>
              <tr className="border-b border-border text-left">
                <th scope="col" className="px-3 py-2 font-medium">
                  {t('instruments.columns.name')}
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  {t('instruments.columns.isin')}
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  {t('instruments.columns.class')}
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  {t('instruments.columns.listing')}
                </th>
                <th scope="col" className="px-3 py-2 text-right font-medium">
                  {t('instruments.columns.lastClose')}
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  {t('instruments.columns.status')}
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  {t('instruments.columns.actions')}
                </th>
              </tr>
            </thead>
            <tbody>
              {data.map((i) => {
                const listing = i.listings[0]
                return (
                  <tr key={i.id} className="border-b border-border align-top">
                    <td className="px-3 py-2">
                      <Link to={`/holdings/${i.id}`} className="font-medium hover:underline">
                        {i.name}
                      </Link>
                    </td>
                    <td className="px-3 py-2">{i.isin ?? '–'}</td>
                    <td className="px-3 py-2">{t(`assetClass.${i.asset_class}`)}</td>
                    <td className="px-3 py-2">
                      {i.manual ? (
                        <Badge>{t('instruments.manual')}</Badge>
                      ) : listing ? (
                        `${listing.ticker} · ${listing.mic} · ${listing.currency}`
                      ) : (
                        '–'
                      )}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {i.last_close ? (
                        <AsOf date={i.last_close.date} source={i.last_close.source}>
                          {eur(i.last_close.close)}
                          {i.stale && (
                            <>
                              {' '}
                              <Badge tone="warn" title={t('holdings.staleHint')}>
                                {t('holdings.stale')}
                              </Badge>
                            </>
                          )}
                        </AsOf>
                      ) : (
                        <span className="text-muted">{t('holdings.noPrice')}</span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      {i.status === 'archived' ? <Badge>{i.status}</Badge> : i.status}
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex flex-wrap gap-1">
                        <Button variant="secondary" onClick={() => setEditing(i)}>
                          {t('instruments.edit')}
                        </Button>
                        {i.manual && (
                          <Button variant="secondary" onClick={() => setPricing(i)}>
                            {t('instruments.enterPrice')}
                          </Button>
                        )}
                        <Button variant="secondary" onClick={() => archive.mutate(i)}>
                          {t(
                            i.status === 'active' ? 'instruments.archive' : 'instruments.unarchive',
                          )}
                        </Button>
                        <Button
                          variant="secondary"
                          onClick={() => {
                            if (window.confirm(t('instruments.deleteConfirm', { name: i.name })))
                              remove.mutate(i)
                          }}
                        >
                          {t('instruments.delete')}
                        </Button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {remove.isError && !blocked && <Alert>{errorMessage(remove.error)}</Alert>}
      <Dialog
        open={blocked !== null}
        onClose={() => setBlocked(null)}
        title={t('instruments.delete')}
      >
        {blocked && (
          <div className="space-y-3">
            <p>{t('instruments.blocked', { name: blocked.name, count: blocked.total })}</p>
            <ul className="list-disc pl-5 text-sm">
              {blocked.rows.map((r) => (
                <li key={r.id}>
                  {r.trade_date} · {r.type} · {r.quantity} · {r.account}
                </li>
              ))}
            </ul>
          </div>
        )}
      </Dialog>

      {editing && <EditDialog instrument={editing} onClose={() => setEditing(null)} />}
      {pricing && <PriceDialog instrument={pricing} onClose={() => setPricing(null)} />}
    </div>
  )
}

function EditDialog({ instrument, onClose }: { instrument: Instrument; onClose: () => void }) {
  const { t } = useTranslation()
  const invalidate = useInvalidateLedger()
  const [name, setName] = useState(instrument.name)
  const [assetClass, setAssetClass] = useState(instrument.asset_class)
  const [issuer, setIssuer] = useState(instrument.issuer ?? '')
  const [productUrl, setProductUrl] = useState(instrument.product_url ?? '')
  const [ter, setTer] = useState(instrument.ter_pct ?? '')
  const [distribution, setDistribution] = useState(instrument.distribution ?? '')
  const [tags, setTags] = useState(instrument.tags.join(', '))
  const [region, setRegion] = useState(instrument.region ?? '')
  const [sector, setSector] = useState(instrument.sector ?? '')
  const [sleeveId, setSleeveId] = useState<number | null>(instrument.sleeve_id ?? null)
  const [benchmark, setBenchmark] = useState(Boolean(instrument.is_benchmark))
  const sleeves = useSleeves()
  const save = useMutation({
    mutationFn: () =>
      unwrap(
        api.PATCH('/api/v1/instruments/{instrument_id}', {
          params: { path: { instrument_id: instrument.id } },
          body: {
            name,
            asset_class: assetClass as (typeof ASSET_CLASSES)[number],
            issuer: issuer || null,
            product_url: productUrl.trim() || null,
            ter_pct: ter === '' ? null : String(ter),
            distribution: (distribution || null) as 'ACC' | 'DIST' | null,
            tags: tags
              .split(',')
              .map((s) => s.trim())
              .filter(Boolean),
            region: region.trim() || null,
            sector: sector.trim() || null,
            sleeve_id: sleeveId,
            is_benchmark: benchmark,
          },
        }),
      ),
    onSuccess: async () => {
      await invalidate()
      onClose()
    },
  })
  function submit(e: FormEvent) {
    e.preventDefault()
    save.mutate()
  }
  return (
    <Dialog open onClose={onClose} title={t('editInstrument.title', { name: instrument.name })}>
      <form onSubmit={submit} className="space-y-4" noValidate>
        <Field label={t('addInstrument.name')}>
          {(p) => <Input value={name} onChange={(e) => setName(e.target.value)} {...p} />}
        </Field>
        <Field label={t('addInstrument.assetClass')}>
          {(p) => (
            <Select value={assetClass} onChange={(e) => setAssetClass(e.target.value)} {...p}>
              {ASSET_CLASSES.map((c) => (
                <option key={c} value={c}>
                  {t(`assetClass.${c}`)}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label={t('addInstrument.issuer')}>
          {(p) => <Input value={issuer} onChange={(e) => setIssuer(e.target.value)} {...p} />}
        </Field>
        <Field label={t('editInstrument.productUrl')} hint={t('editInstrument.productUrlHint')}>
          {(p) => (
            <Input
              type="url"
              inputMode="url"
              placeholder="https://"
              value={productUrl}
              onChange={(e) => setProductUrl(e.target.value)}
              {...p}
            />
          )}
        </Field>
        <Field label={t('editInstrument.ter')}>
          {(p) => (
            <Input
              value={ter}
              inputMode="decimal"
              onChange={(e) => setTer(e.target.value)}
              {...p}
            />
          )}
        </Field>
        <Field label={t('addInstrument.distribution')}>
          {(p) => (
            <Select value={distribution} onChange={(e) => setDistribution(e.target.value)} {...p}>
              <option value="">{t('addInstrument.none')}</option>
              <option value="ACC">{t('addInstrument.acc')}</option>
              <option value="DIST">{t('addInstrument.dist')}</option>
            </Select>
          )}
        </Field>
        <Field label={t('editInstrument.tags')}>
          {(p) => <Input value={tags} onChange={(e) => setTags(e.target.value)} {...p} />}
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t('editInstrument.region')} hint={t('editInstrument.regionHint')}>
            {(p) => (
              <Input
                value={region}
                maxLength={40}
                onChange={(e) => setRegion(e.target.value)}
                {...p}
              />
            )}
          </Field>
          <Field label={t('editInstrument.sector')}>
            {(p) => (
              <Input
                value={sector}
                maxLength={60}
                onChange={(e) => setSector(e.target.value)}
                {...p}
              />
            )}
          </Field>
        </div>
        <Field label={t('editInstrument.sleeve')} hint={t('editInstrument.sleeveHint')}>
          {(p) => (
            <Select
              value={sleeveId ?? ''}
              onChange={(e) => setSleeveId(e.target.value ? Number(e.target.value) : null)}
              {...p}
            >
              <option value="">{t('editInstrument.noSleeve')}</option>
              {sleeves.data?.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <div className="space-y-1">
          <Checkbox
            label={t('editInstrument.benchmark')}
            checked={benchmark}
            onChange={(e) => setBenchmark(e.target.checked)}
          />
          <p className="text-sm text-muted">{t('editInstrument.benchmarkHint')}</p>
        </div>
        {save.isError && <Alert>{errorMessage(save.error)}</Alert>}
        <Button type="submit" disabled={save.isPending}>
          {t('editInstrument.save')}
        </Button>
      </form>
    </Dialog>
  )
}

function PriceDialog({ instrument, onClose }: { instrument: Instrument; onClose: () => void }) {
  const { t } = useTranslation()
  const invalidate = useInvalidateLedger()
  const [day, setDay] = useState(new Date().toISOString().slice(0, 10))
  const [close, setClose] = useState('')
  const save = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST('/api/v1/instruments/{instrument_id}/prices', {
          params: { path: { instrument_id: instrument.id } },
          body: { date: day, close },
        }),
      ),
    onSuccess: async () => {
      await invalidate()
      onClose()
    },
  })
  function submit(e: FormEvent) {
    e.preventDefault()
    save.mutate()
  }
  return (
    <Dialog open onClose={onClose} title={t('priceEntry.title', { name: instrument.name })}>
      <form onSubmit={submit} className="space-y-4" noValidate>
        <p className="text-sm text-muted">{t('priceEntry.hint')}</p>
        <Field label={t('priceEntry.date')}>
          {(p) => <Input type="date" value={day} onChange={(e) => setDay(e.target.value)} {...p} />}
        </Field>
        <Field label={t('priceEntry.close')}>
          {(p) => (
            <Input
              value={close}
              inputMode="decimal"
              onChange={(e) => setClose(e.target.value)}
              {...p}
            />
          )}
        </Field>
        {save.isError && <Alert>{errorMessage(save.error)}</Alert>}
        <Button type="submit" disabled={save.isPending || !close}>
          {t('priceEntry.submit')}
        </Button>
      </form>
    </Dialog>
  )
}
