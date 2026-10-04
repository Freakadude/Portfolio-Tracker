import { useMutation } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { api, errorMessage, unwrap } from '../api/client'
import { useInvalidateLedger, type Resolution } from '../api/queries'
import { cn } from '../lib/cn'
import { Badge, Dialog } from './display'
import { Alert, Button, Field, Input, Select } from './ui'

export const ASSET_CLASSES = ['ETF', 'ETC', 'EQUITY', 'BOND', 'FUND', 'CASH', 'OTHER'] as const
type AssetClass = (typeof ASSET_CLASSES)[number]
type Mode = 'isin' | 'hand'

interface Props {
  open: boolean
  onClose: () => void
  onAdded?: () => void
}

export function AddInstrumentDialog({ open, onClose, onAdded }: Props) {
  const { t } = useTranslation()
  const [mode, setMode] = useState<Mode>('isin')
  return (
    <Dialog open={open} onClose={onClose} title={t('addInstrument.title')} wide>
      <div role="tablist" className="mb-4 flex gap-1">
        {(['isin', 'hand'] as const).map((m) => (
          <button
            key={m}
            role="tab"
            aria-selected={mode === m}
            onClick={() => setMode(m)}
            className={cn(
              'rounded-md px-3 py-2 text-sm',
              mode === m ? 'bg-primary text-primary-foreground' : 'hover:bg-border/40',
            )}
          >
            {t(m === 'isin' ? 'addInstrument.byIsin' : 'addInstrument.byHand')}
          </button>
        ))}
      </div>
      {mode === 'isin' ? (
        <ByIsin onDone={() => (onAdded?.(), onClose())} />
      ) : (
        <ByHand onDone={() => (onAdded?.(), onClose())} />
      )}
    </Dialog>
  )
}

function ByIsin({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation()
  const invalidate = useInvalidateLedger()
  const [isin, setIsin] = useState('')
  const [chosen, setChosen] = useState<number | null>(null)
  const [name, setName] = useState('')
  const [assetClass, setAssetClass] = useState<AssetClass>('ETF')
  const [issuer, setIssuer] = useState('')
  const [distribution, setDistribution] = useState('')
  const [currency, setCurrency] = useState('')
  const [pickError, setPickError] = useState<string | null>(null)

  const lookup = useMutation({
    mutationFn: (value: string) =>
      unwrap(api.GET('/api/v1/instruments/resolve', { params: { query: { isin: value } } })),
    onSuccess: (r: Resolution) => {
      setName(r.name)
      setAssetClass(
        (ASSET_CLASSES as readonly string[]).includes(r.asset_class)
          ? (r.asset_class as AssetClass)
          : 'ETF',
      )
      setIssuer(r.issuer ?? '')
      const first = r.candidates.findIndex((c) => c.usable)
      setChosen(first >= 0 ? first : null)
      setCurrency(first >= 0 ? r.candidates[first].currency : '')
    },
  })
  const resolution = lookup.data

  const add = useMutation({
    mutationFn: () => {
      const candidate = resolution!.candidates[chosen!]
      return unwrap(
        api.POST('/api/v1/instruments', {
          body: {
            isin: resolution!.isin,
            manual: false,
            name,
            asset_class: assetClass,
            issuer: issuer || null,
            domicile: resolution!.domicile,
            distribution: (distribution || null) as 'ACC' | 'DIST' | null,
            listing: { mic: candidate.mic, ticker: candidate.ticker, currency },
          },
        }),
      )
    },
    onSuccess: async () => {
      await invalidate()
      onDone()
    },
  })

  function submitLookup(e: FormEvent) {
    e.preventDefault()
    lookup.mutate(isin.trim())
  }
  function submitAdd(e: FormEvent) {
    e.preventDefault()
    if (chosen === null) return setPickError(t('addInstrument.pickRequired'))
    if (!name.trim()) return setPickError(t('addInstrument.nameRequired'))
    setPickError(null)
    add.mutate()
  }

  return (
    <div className="space-y-4">
      <form onSubmit={submitLookup} className="flex items-end gap-2" noValidate>
        <div className="flex-1">
          <Field label={t('addInstrument.isin')} hint={t('addInstrument.isinHint')}>
            {(p) => (
              <Input
                value={isin}
                onChange={(e) => setIsin(e.target.value)}
                autoComplete="off"
                autoFocus
                {...p}
              />
            )}
          </Field>
        </div>
        <Button type="submit" disabled={lookup.isPending || !isin.trim()}>
          {t(lookup.isPending ? 'addInstrument.looking' : 'addInstrument.lookup')}
        </Button>
      </form>
      {lookup.isError && <Alert>{errorMessage(lookup.error)}</Alert>}

      {resolution && resolution.candidates.length === 0 && (
        <p className="text-muted">{t('addInstrument.noListings')}</p>
      )}

      {resolution && resolution.candidates.length > 0 && (
        <form onSubmit={submitAdd} className="space-y-4" noValidate>
          <fieldset className="space-y-2">
            <legend className="mb-1 text-sm font-medium">{t('addInstrument.pick')}</legend>
            {resolution.candidates.map((c, i) => (
              <label
                key={`${c.mic}-${c.ticker}`}
                className={cn(
                  'flex items-start gap-3 rounded-md border border-border p-3',
                  !c.usable && 'opacity-60',
                  chosen === i && 'border-primary',
                )}
              >
                <input
                  type="radio"
                  name="listing"
                  className="mt-1"
                  disabled={!c.usable}
                  checked={chosen === i}
                  onChange={() => {
                    setChosen(i)
                    setCurrency(c.currency)
                  }}
                />
                <span className="flex-1">
                  <span className="font-medium">
                    {t('addInstrument.listingLabel', {
                      exchange: c.exchange_name,
                      ticker: c.ticker,
                      currency: c.currency,
                    })}
                  </span>{' '}
                  <Badge tone={c.currency_confirmed ? 'good' : 'warn'}>
                    {c.currency_confirmed
                      ? t('addInstrument.confirmed', { source: c.confirmed_by })
                      : t('addInstrument.guess')}
                  </Badge>
                  {c.warning && <span className="mt-1 block text-sm text-muted">{c.warning}</span>}
                </span>
              </label>
            ))}
          </fieldset>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t('addInstrument.name')}>
              {(p) => <Input value={name} onChange={(e) => setName(e.target.value)} {...p} />}
            </Field>
            <Field label={t('addInstrument.assetClass')}>
              {(p) => (
                <Select
                  value={assetClass}
                  onChange={(e) => setAssetClass(e.target.value as AssetClass)}
                  {...p}
                >
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
            <Field label={t('addInstrument.distribution')}>
              {(p) => (
                <Select
                  value={distribution}
                  onChange={(e) => setDistribution(e.target.value)}
                  {...p}
                >
                  <option value="">{t('addInstrument.none')}</option>
                  <option value="ACC">{t('addInstrument.acc')}</option>
                  <option value="DIST">{t('addInstrument.dist')}</option>
                </Select>
              )}
            </Field>
            <Field label={t('addInstrument.currency')} hint={t('addInstrument.currencyHint')}>
              {(p) => (
                <Input
                  value={currency}
                  maxLength={3}
                  onChange={(e) => setCurrency(e.target.value.toUpperCase())}
                  {...p}
                />
              )}
            </Field>
          </div>
          {pickError && <Alert>{pickError}</Alert>}
          {add.isError && <Alert>{errorMessage(add.error)}</Alert>}
          <Button type="submit" disabled={add.isPending}>
            {t('addInstrument.submit')}
          </Button>
        </form>
      )}
    </div>
  )
}

function ByHand({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation()
  const invalidate = useInvalidateLedger()
  const [name, setName] = useState('')
  const [assetClass, setAssetClass] = useState<AssetClass>('BOND')
  const [currency, setCurrency] = useState('EUR')
  const [isin, setIsin] = useState('')
  const [errors, setErrors] = useState<{ name?: string; currency?: string }>({})

  const add = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST('/api/v1/instruments', {
          body: {
            name: name.trim(),
            asset_class: assetClass,
            manual: true,
            currency: currency.toUpperCase(),
            isin: isin.trim() || null,
          },
        }),
      ),
    onSuccess: async () => {
      await invalidate()
      onDone()
    },
  })

  function submit(e: FormEvent) {
    e.preventDefault()
    const next: typeof errors = {}
    if (!name.trim()) next.name = t('addInstrument.nameRequired')
    if (!/^[A-Za-z]{3}$/.test(currency)) next.currency = t('addInstrument.currencyRequired')
    setErrors(next)
    if (Object.keys(next).length === 0) add.mutate()
  }

  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <p className="text-muted">{t('addInstrument.handHint')}</p>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t('addInstrument.name')} error={errors.name}>
          {(p) => <Input value={name} onChange={(e) => setName(e.target.value)} autoFocus {...p} />}
        </Field>
        <Field label={t('addInstrument.assetClass')}>
          {(p) => (
            <Select
              value={assetClass}
              onChange={(e) => setAssetClass(e.target.value as AssetClass)}
              {...p}
            >
              {ASSET_CLASSES.map((c) => (
                <option key={c} value={c}>
                  {t(`assetClass.${c}`)}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field
          label={t('addInstrument.currency')}
          error={errors.currency}
          hint={t('addInstrument.currencyHint')}
        >
          {(p) => (
            <Input
              value={currency}
              maxLength={3}
              onChange={(e) => setCurrency(e.target.value.toUpperCase())}
              {...p}
            />
          )}
        </Field>
        <Field label={`${t('addInstrument.isin')} (${t('addInstrument.none').toLowerCase()})`}>
          {(p) => <Input value={isin} onChange={(e) => setIsin(e.target.value)} {...p} />}
        </Field>
      </div>
      {add.isError && <Alert>{errorMessage(add.error)}</Alert>}
      <Button type="submit" disabled={add.isPending}>
        {t('addInstrument.submit')}
      </Button>
    </form>
  )
}
