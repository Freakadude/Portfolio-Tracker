import { keepPreviousData, useMutation, useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { ApiProblem, api, errorMessage, unwrap } from '../api/client'
import {
  useAccounts,
  useInstruments,
  useInvalidateLedger,
  type AmountPreview,
  type SellPreview,
  type Transaction,
  type TransactionInput,
} from '../api/queries'
import { isPositiveDecimal, reciprocal, trimDecimal } from '../lib/decimal'
import { useFormat } from '../lib/useFormat'
import { Delta } from './display'
import { Alert, Button, Field, Input, Select, Textarea } from './ui'

export const TYPES = [
  'buy',
  'sell',
  'dividend',
  'interest',
  'fee',
  'tax',
  'split',
  'transfer_in',
  'transfer_out',
  'deposit',
  'withdrawal',
] as const
export type TxType = (typeof TYPES)[number]

const TRADE: TxType[] = ['buy', 'sell']
const TRANSFER: TxType[] = ['transfer_in', 'transfer_out']
const CASH: TxType[] = ['dividend', 'interest', 'fee', 'tax', 'deposit', 'withdrawal']

/** Which fields each type shows (FR-TX-01: the form shows only what a type needs). */
export function fieldsFor(type: TxType) {
  const trade = TRADE.includes(type)
  const transfer = TRANSFER.includes(type)
  return {
    instrument: trade || transfer || type === 'split' || type === 'dividend' || type === 'interest',
    instrumentRequired: type !== 'interest',
    units: trade || transfer,
    price: trade || transfer,
    currency: trade || transfer,
    fees: trade,
    taxes: trade,
    amount: CASH.includes(type) || type === 'transfer_in',
    withholding: type === 'dividend' || type === 'interest',
    ratio: type === 'split',
  }
}

interface Values {
  type: TxType
  accountId: string
  tradeDate: string
  settleDate: string
  instrumentId: string
  quantity: string
  price: string
  currency: string
  fxRate: string // foreign units per EUR, as the owner's broker states it; empty = ECB
  fees: string
  feesCurrency: string
  taxes: string
  amount: string
  ratio: string
  note: string
}

const today = () => new Date().toISOString().slice(0, 10)

const EMPTY: Values = {
  type: 'buy',
  accountId: '',
  tradeDate: today(),
  settleDate: '',
  instrumentId: '',
  quantity: '',
  price: '',
  currency: 'EUR',
  fxRate: '',
  fees: '',
  feesCurrency: 'EUR',
  taxes: '',
  amount: '',
  ratio: '',
  note: '',
}

function fromTransaction(tx: Transaction): Values {
  const rate = tx.currency !== 'EUR' ? reciprocal(tx.fx_rate_to_eur, 6) : null
  const blank = (v: string) => (Number(v) === 0 ? '' : trimDecimal(v))
  return {
    type: tx.type as TxType,
    accountId: String(tx.account_id),
    tradeDate: tx.trade_date,
    settleDate: tx.settle_date ?? '',
    instrumentId: tx.instrument_id ? String(tx.instrument_id) : '',
    quantity: blank(tx.quantity),
    price:
      Number(tx.price) === 0 && !TRADE.includes(tx.type as TxType) ? '' : trimDecimal(tx.price),
    currency: tx.currency,
    fxRate: rate ? trimDecimal(rate) : '',
    fees: blank(tx.fees),
    feesCurrency: tx.fees_currency,
    taxes: blank(tx.taxes),
    amount:
      CASH.includes(tx.type as TxType) || tx.type === 'transfer_in'
        ? trimDecimal(tx.net_amount_eur ?? '')
        : '',
    ratio: tx.ratio ? trimDecimal(tx.ratio) : '',
    note: tx.note ?? '',
  }
}

/** Server field names to the form's field names, so a server message lands next to its input. */
const SERVER_FIELD: Record<string, keyof Values> = {
  account_id: 'accountId',
  trade_date: 'tradeDate',
  settle_date: 'settleDate',
  instrument_id: 'instrumentId',
  quantity: 'quantity',
  price: 'price',
  currency: 'currency',
  fx_rate_to_eur: 'fxRate',
  fees: 'fees',
  fees_currency: 'feesCurrency',
  taxes: 'taxes',
  net_amount_eur: 'amount',
  ratio: 'ratio',
}

/** The request body for the API from what the owner typed. Empty optional fields are left out. */
export function buildBody(v: Values): TransactionInput {
  const f = fieldsFor(v.type)
  const body: Record<string, unknown> = {
    account_id: Number(v.accountId),
    type: v.type,
    trade_date: v.tradeDate,
    fees: '0',
    taxes: '0',
    note: v.note.trim() || null,
  }
  if (v.settleDate) body.settle_date = v.settleDate
  if (f.instrument && v.instrumentId) body.instrument_id = Number(v.instrumentId)
  if (f.units) body.quantity = v.quantity
  if (f.price) body.price = v.price || '0'
  if (f.currency) {
    body.currency = v.currency.toUpperCase()
    if (v.currency.toUpperCase() !== 'EUR' && v.fxRate.trim()) {
      body.fx_rate_to_eur = reciprocal(v.fxRate) ?? undefined // exact, rounded as the server does
    }
  }
  if (f.fees && v.fees) {
    body.fees = v.fees
    body.fees_currency = v.feesCurrency.toUpperCase() || 'EUR'
  }
  if (f.taxes && v.taxes) body.taxes = v.taxes
  if (f.withholding && v.taxes) body.taxes = v.taxes
  if (f.amount && v.amount) body.net_amount_eur = v.amount
  if (f.ratio) body.ratio = v.ratio
  return body as unknown as TransactionInput
}

/** Drop undefined entries so a missing prefill never overrides a default. */
function definedOnly<T extends object>(obj: T | undefined): Partial<T> {
  return Object.fromEntries(
    Object.entries(obj ?? {}).filter(([, v]) => v !== undefined),
  ) as Partial<T>
}

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), ms)
    return () => clearTimeout(id)
  }, [value, ms])
  return debounced
}

interface Props {
  onDone: () => void
  /** Pre-filled values, for example from the position page's Buy and Sell buttons. */
  initial?: Partial<Pick<Values, 'type' | 'instrumentId' | 'accountId'>>
  editing?: Transaction
}

export function TransactionForm({ onDone, initial, editing }: Props) {
  const { t } = useTranslation()
  const { eur, num, qty } = useFormat()
  const invalidate = useInvalidateLedger()
  const accounts = useAccounts()
  const instruments = useInstruments('active')
  const [v, setV] = useState<Values>(() =>
    editing ? fromTransaction(editing) : { ...EMPTY, ...definedOnly(initial) },
  )
  const [initialValues] = useState(v)
  const [errors, setErrors] = useState<Partial<Record<keyof Values, string>>>({})
  const fields = fieldsFor(v.type)
  const set = <K extends keyof Values>(key: K, value: Values[K]) => {
    setV((prev) => ({ ...prev, [key]: value }))
    setErrors((prev) => ({ ...prev, [key]: undefined }))
  }

  // default account: the only one, or the first
  useEffect(() => {
    if (!v.accountId && accounts.data?.length)
      setV((p) => ({ ...p, accountId: String(accounts.data![0].id) }))
  }, [accounts.data, v.accountId])

  const instrument = instruments.data?.find((i) => String(i.id) === v.instrumentId)
  // choosing an instrument fills in its trading currency
  function chooseInstrument(id: string) {
    const picked = instruments.data?.find((i) => String(i.id) === id)
    setV((p) => ({
      ...p,
      instrumentId: id,
      currency: picked?.listings[0]?.currency ?? p.currency,
      fxRate: '',
    }))
    setErrors((p) => ({ ...p, instrumentId: undefined }))
  }

  const foreign =
    fields.currency && /^[A-Za-z]{3}$/.test(v.currency) && v.currency.toUpperCase() !== 'EUR'
  const prefill = useQuery({
    queryKey: ['fx-prefill', v.currency.toUpperCase(), v.tradeDate],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/transactions/fx-prefill', {
          params: { query: { currency: v.currency.toUpperCase(), date: v.tradeDate } },
        }),
      ),
    enabled: Boolean(foreign && v.tradeDate),
    retry: false,
  })

  // --- the live preview of a sale (FR-TX-04) ---
  const sellBody = useMemo(() => {
    if (editing || v.type !== 'sell') return null
    if (!v.accountId || !v.instrumentId || !v.tradeDate) return null
    if (!isPositiveDecimal(v.quantity) || !/^\s*\d+([.,]\d+)?\s*$/.test(v.price)) return null
    if (foreign && !v.fxRate.trim() && !prefill.data) return null
    return buildBody(v)
  }, [v, editing, foreign, prefill.data])
  // --- the calculated amount of a buy or sell, from the server's own arithmetic (FR-TX-14) ---
  const amountBody = useMemo(() => {
    if (!TRADE.includes(v.type)) return null
    if (!v.accountId || !v.instrumentId || !v.tradeDate) return null
    if (!isPositiveDecimal(v.quantity) || !/^\s*\d+([.,]\d+)?\s*$/.test(v.price)) return null
    if (foreign && !v.fxRate.trim() && !prefill.data) return null
    return buildBody(v)
  }, [v, foreign, prefill.data])
  const debouncedAmount = useDebounced(amountBody, 400)
  const amount = useQuery({
    queryKey: ['amount-preview', debouncedAmount],
    queryFn: () =>
      unwrap(api.POST('/api/v1/transactions/preview-amount', { body: debouncedAmount! })),
    enabled: debouncedAmount !== null,
    placeholderData: keepPreviousData, // no flicker while the next figure is on its way
    retry: false,
  })
  const debouncedSell = useDebounced(sellBody, 400)
  const preview = useQuery({
    queryKey: ['sell-preview', debouncedSell],
    queryFn: () => unwrap(api.POST('/api/v1/transactions/preview-sell', { body: debouncedSell! })),
    enabled: debouncedSell !== null,
    retry: false,
  })

  const save = useMutation({
    mutationFn: () => {
      if (editing) {
        const next = buildBody(v) as unknown as Record<string, unknown>
        const before = buildBody(initialValues) as unknown as Record<string, unknown>
        // A different type needs different fields, so everything is sent again; otherwise only
        // what the owner changed is.
        const changes: Record<string, unknown> = v.type !== initialValues.type ? { ...next } : {}
        if (v.type === initialValues.type) {
          for (const key of Object.keys(next)) {
            if (JSON.stringify(next[key]) !== JSON.stringify(before[key])) changes[key] = next[key]
          }
        }
        return unwrap(
          api.PATCH('/api/v1/transactions/{transaction_id}', {
            params: { path: { transaction_id: editing.id } },
            body: changes,
          }),
        )
      }
      return unwrap(api.POST('/api/v1/transactions', { body: buildBody(v) }))
    },
    onSuccess: async () => {
      await invalidate()
      onDone()
    },
    onError: (err) => {
      if (err instanceof ApiProblem && err.errors.length) {
        const mapped: Partial<Record<keyof Values, string>> = {}
        for (const e of err.errors) mapped[SERVER_FIELD[e.field] ?? 'note'] = e.message
        setErrors(mapped)
      }
    },
  })

  function validate(): boolean {
    const next: Partial<Record<keyof Values, string>> = {}
    const need = (key: keyof Values) => {
      if (!String(v[key]).trim()) next[key] = t('txForm.required')
    }
    const positive = (key: keyof Values) => {
      if (!String(v[key]).trim()) next[key] = t('txForm.required')
      else if (!isPositiveDecimal(String(v[key]))) next[key] = t('txForm.positive')
    }
    need('accountId')
    need('tradeDate')
    if (fields.instrument && fields.instrumentRequired) need('instrumentId')
    if (fields.units) positive('quantity')
    if (fields.price) {
      need('price')
      if (v.price.trim() && !/^\s*\d+([.,]\d+)?\s*$/.test(v.price))
        next.price = t('txForm.positive')
    }
    if (fields.currency) need('currency')
    if (v.type !== 'transfer_in' && fields.amount) positive('amount')
    if (v.type === 'transfer_in' && v.amount.trim() && !isPositiveDecimal(v.amount))
      next.amount = t('txForm.positive')
    if (fields.ratio) positive('ratio')
    if (v.fxRate.trim() && !isPositiveDecimal(v.fxRate)) next.fxRate = t('txForm.positive')
    setErrors(next)
    return Object.keys(next).length === 0
  }

  function submit(e: FormEvent) {
    e.preventDefault()
    if (validate()) save.mutate()
  }

  const rateInUse = v.fxRate.trim()
    ? reciprocal(v.fxRate, 6)
    : prefill.data
      ? trimDecimal(prefill.data.fx_rate_to_eur).slice(0, 10)
      : null
  const noAccount = accounts.data && accounts.data.length === 0
  const noInstrument =
    instruments.data &&
    instruments.data.length === 0 &&
    fields.instrument &&
    fields.instrumentRequired

  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      {noAccount && <Alert>{t('transactions.noAccounts')}</Alert>}
      {noInstrument && <Alert>{t('transactions.noInstruments')}</Alert>}
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t('txForm.type')}>
          {(p) => (
            <Select value={v.type} onChange={(e) => set('type', e.target.value as TxType)} {...p}>
              {TYPES.map((x) => (
                <option key={x} value={x}>
                  {t(`transactions.types.${x}`)}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label={t('txForm.account')} error={errors.accountId}>
          {(p) => (
            <Select value={v.accountId} onChange={(e) => set('accountId', e.target.value)} {...p}>
              {accounts.data?.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label={t('txForm.date')} error={errors.tradeDate}>
          {(p) => (
            <Input
              type="date"
              value={v.tradeDate}
              onChange={(e) => set('tradeDate', e.target.value)}
              {...p}
            />
          )}
        </Field>
        <Field label={t('txForm.settle')} error={errors.settleDate}>
          {(p) => (
            <Input
              type="date"
              value={v.settleDate}
              onChange={(e) => set('settleDate', e.target.value)}
              {...p}
            />
          )}
        </Field>
        {fields.instrument && (
          <div className="sm:col-span-2">
            <Field
              label={t(
                fields.instrumentRequired ? 'txForm.instrument' : 'txForm.instrumentOptional',
              )}
              error={errors.instrumentId}
            >
              {(p) => (
                <Select
                  value={v.instrumentId}
                  onChange={(e) => chooseInstrument(e.target.value)}
                  {...p}
                >
                  <option value="">{t('txForm.choose')}</option>
                  {instruments.data?.map((i) => (
                    <option key={i.id} value={i.id}>
                      {i.name}
                      {i.listings[0] ? ` (${i.listings[0].ticker})` : ''}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
          </div>
        )}
        {fields.units && (
          <Field label={t('txForm.quantity')} error={errors.quantity}>
            {(p) => (
              <Input
                value={v.quantity}
                inputMode="decimal"
                onChange={(e) => set('quantity', e.target.value)}
                {...p}
              />
            )}
          </Field>
        )}
        {fields.price && (
          <Field label={t('txForm.price')} error={errors.price}>
            {(p) => (
              <Input
                value={v.price}
                inputMode="decimal"
                onChange={(e) => set('price', e.target.value)}
                {...p}
              />
            )}
          </Field>
        )}
        {fields.currency && (
          <Field label={t('txForm.currency')} error={errors.currency}>
            {(p) => (
              <Input
                value={v.currency}
                maxLength={3}
                onChange={(e) => set('currency', e.target.value.toUpperCase())}
                {...p}
              />
            )}
          </Field>
        )}
        {foreign && (
          <Field
            label={t('txForm.fx')}
            error={errors.fxRate}
            hint={
              prefill.data
                ? t('txForm.fxPrefilled', { date: prefill.data.rate_date })
                : prefill.isError
                  ? t('txForm.fxMissing')
                  : undefined
            }
          >
            {(p) => (
              <Input
                value={v.fxRate}
                inputMode="decimal"
                placeholder={prefill.data ? trimDecimal(prefill.data.rate_per_eur) : ''}
                onChange={(e) => set('fxRate', e.target.value)}
                {...p}
              />
            )}
          </Field>
        )}
        {foreign && rateInUse && (
          <p className="self-end text-sm text-muted sm:col-span-2">
            {t('txForm.fxUsed', { currency: v.currency.toUpperCase(), rate: num(rateInUse) })}
          </p>
        )}
        {fields.fees && (
          <>
            <Field label={t('txForm.fees')} error={errors.fees}>
              {(p) => (
                <Input
                  value={v.fees}
                  inputMode="decimal"
                  onChange={(e) => set('fees', e.target.value)}
                  {...p}
                />
              )}
            </Field>
            <Field label={t('txForm.feesCurrency')} error={errors.feesCurrency}>
              {(p) => (
                <Input
                  value={v.feesCurrency}
                  maxLength={3}
                  onChange={(e) => set('feesCurrency', e.target.value.toUpperCase())}
                  {...p}
                />
              )}
            </Field>
          </>
        )}
        {fields.taxes && (
          <Field label={t('txForm.taxes')} error={errors.taxes}>
            {(p) => (
              <Input
                value={v.taxes}
                inputMode="decimal"
                onChange={(e) => set('taxes', e.target.value)}
                {...p}
              />
            )}
          </Field>
        )}
        {fields.amount && (
          <Field
            label={t(
              v.type === 'dividend'
                ? 'txForm.amountDividend'
                : v.type === 'transfer_in'
                  ? 'txForm.amountCarried'
                  : 'txForm.amount',
            )}
            error={errors.amount}
          >
            {(p) => (
              <Input
                value={v.amount}
                inputMode="decimal"
                onChange={(e) => set('amount', e.target.value)}
                {...p}
              />
            )}
          </Field>
        )}
        {fields.withholding && (
          <Field label={t('txForm.withholding')} error={errors.taxes}>
            {(p) => (
              <Input
                value={v.taxes}
                inputMode="decimal"
                onChange={(e) => set('taxes', e.target.value)}
                {...p}
              />
            )}
          </Field>
        )}
        {fields.ratio && (
          <Field label={t('txForm.ratio')} hint={t('txForm.ratioHint')} error={errors.ratio}>
            {(p) => (
              <Input
                value={v.ratio}
                inputMode="decimal"
                onChange={(e) => set('ratio', e.target.value)}
                {...p}
              />
            )}
          </Field>
        )}
        <div className="sm:col-span-2">
          <Field label={t('txForm.note')} error={errors.note}>
            {(p) => (
              <Textarea
                rows={2}
                value={v.note}
                onChange={(e) => set('note', e.target.value)}
                {...p}
              />
            )}
          </Field>
        </div>
      </div>

      {TRADE.includes(v.type) && (
        <section
          aria-live="polite"
          aria-label={t('amountPreview.title')}
          className="rounded-md border border-border p-3"
        >
          <h3 className="mb-2 font-medium">{t('amountPreview.title')}</h3>
          {amountBody === null ? (
            <p className="text-sm text-muted">{t('amountPreview.waiting')}</p>
          ) : amount.isError ? (
            <Alert>{errorMessage(amount.error)}</Alert>
          ) : amount.data ? (
            <AmountLines data={amount.data} type={v.type} />
          ) : (
            <p className="text-sm text-muted">{t('amountPreview.waiting')}</p>
          )}
        </section>
      )}

      {v.type === 'sell' && !editing && (
        <section
          aria-live="polite"
          aria-label={t('sellPreview.title')}
          className="rounded-md border border-border p-3"
        >
          <h3 className="mb-2 font-medium">{t('sellPreview.title')}</h3>
          {preview.isError ? (
            <Alert>{errorMessage(preview.error)}</Alert>
          ) : preview.data ? (
            <PreviewTable data={preview.data} />
          ) : (
            <p className="text-sm text-muted">{t('sellPreview.waiting')}</p>
          )}
        </section>
      )}

      {save.isError && !Object.keys(errors).length && <Alert>{errorMessage(save.error)}</Alert>}
      <Button type="submit" disabled={save.isPending || Boolean(noAccount)}>
        {t(save.isPending ? 'txForm.saving' : 'txForm.save')}
      </Button>
      <span className="sr-only">{instrument?.name}</span>
      <span className="sr-only">
        {eur(0)}
        {qty(0)}
      </span>
    </form>
  )
}

function AmountLines({ data, type }: { data: AmountPreview; type: TxType }) {
  const { t } = useTranslation()
  const { eur } = useFormat()
  const row = (label: string, value: string, strong = false) => (
    <tr className={strong ? 'border-t border-border font-medium' : ''}>
      <th scope="row" className="py-1 text-left font-normal">
        {label}
      </th>
      <td className="py-1 text-right tabular-nums">{value}</td>
    </tr>
  )
  const net = data.net_amount_eur
  return (
    <table className="w-full text-sm">
      <caption className="sr-only">{t('amountPreview.caption')}</caption>
      <tbody>
        {row(t('amountPreview.gross'), eur(data.gross_eur))}
        {Number(data.fees_eur) !== 0 && row(t('amountPreview.fees'), eur(data.fees_eur))}
        {Number(data.taxes_eur) !== 0 && row(t('amountPreview.taxes'), eur(data.taxes_eur))}
        {row(
          t(type === 'buy' ? 'amountPreview.paid' : 'amountPreview.received'),
          eur(type === 'buy' ? net.replace(/^-/, '') : net),
          true,
        )}
      </tbody>
    </table>
  )
}

function PreviewTable({ data }: { data: SellPreview }) {
  const { t } = useTranslation()
  const { eur, qty } = useFormat()
  return (
    <div className="space-y-2">
      <table className="w-full text-sm">
        <caption className="sr-only">{t('sellPreview.caption')}</caption>
        <thead>
          <tr className="border-b border-border">
            <th scope="col" className="py-1 text-left font-medium">
              {t('sellPreview.lot')}
            </th>
            <th scope="col" className="py-1 text-right font-medium">
              {t('sellPreview.units')}
            </th>
            <th scope="col" className="py-1 text-right font-medium">
              {t('sellPreview.cost')}
            </th>
            <th scope="col" className="py-1 text-right font-medium">
              {t('sellPreview.proceeds')}
            </th>
            <th scope="col" className="py-1 text-right font-medium">
              {t('sellPreview.result')}
            </th>
          </tr>
        </thead>
        <tbody>
          {data.matches.map((m) => (
            <tr key={m.lot_buy_transaction_id} className="border-b border-border">
              <td className="py-1">{m.lot_trade_date ?? '–'}</td>
              <td className="py-1 text-right tabular-nums">{qty(m.quantity)}</td>
              <td className="py-1 text-right tabular-nums">{eur(m.cost_eur)}</td>
              <td className="py-1 text-right tabular-nums">{eur(m.proceeds_eur)}</td>
              <td className="py-1 text-right">
                <Delta value={m.realized_pnl_eur} />
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="font-medium">
            <th scope="row" className="py-1 text-left">
              {t('sellPreview.total')}
            </th>
            <td />
            <td className="py-1 text-right tabular-nums">{eur(data.cost_eur)}</td>
            <td className="py-1 text-right tabular-nums">{eur(data.net_proceeds_eur)}</td>
            <td className="py-1 text-right">
              <Delta value={data.realized_pnl_eur} />
            </td>
          </tr>
        </tfoot>
      </table>
      <p className="text-sm">
        {t('sellPreview.realized')}: <Delta value={data.realized_pnl_eur} /> (
        <Delta value={data.realized_pct} kind="pct" />)
      </p>
      <p className="text-sm text-muted">
        {t('sellPreview.remaining')}:{' '}
        {t('sellPreview.remainingValue', {
          units: qty(data.remaining_quantity),
          cost: eur(data.remaining_cost_basis_eur),
        })}
      </p>
    </div>
  )
}
