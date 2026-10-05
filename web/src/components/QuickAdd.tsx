import { useMutation } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { ApiProblem, api, errorMessage, unwrap } from '../api/client'
import {
  useAccounts,
  useInstruments,
  useInvalidateLedger,
  type TransactionInput,
} from '../api/queries'
import { isPositiveDecimal, wholeUnits } from '../lib/decimal'
import { Dialog } from './display'
import { Alert, Button, Field, Input, Select } from './ui'

interface Row {
  key: number
  instrumentId: string
  weight: string
  units: string
  price: string
  fees: string
}

let nextKey = 1
const blank = (): Row => ({
  key: nextKey++,
  instrumentId: '',
  weight: '',
  units: '',
  price: '',
  fees: '',
})

const today = () => new Date().toISOString().slice(0, 10)

/** Several buys at once, saved together or not at all (FR-TX-11). An amount can be split over
 * the rows by weight; it buys whole units only (Q8) and the rest stays unspent. */
export function QuickAdd({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation()
  return (
    <Dialog open={open} onClose={onClose} title={t('quickAdd.title')} wide>
      <QuickAddForm onDone={onClose} />
    </Dialog>
  )
}

function QuickAddForm({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation()
  const accounts = useAccounts()
  const instruments = useInstruments()
  const invalidate = useInvalidateLedger()
  const [account, setAccount] = useState('')
  const [date, setDate] = useState(today)
  const [amount, setAmount] = useState('')
  const [rows, setRows] = useState<Row[]>(() => [blank(), blank()])
  const [problems, setProblems] = useState<string[]>([])

  const accountId = account || String(accounts.data?.[0]?.id ?? '')
  const priceOf = (instrumentId: string) => {
    const found = instruments.data?.find((i) => String(i.id) === instrumentId)
    return found?.last_close?.close ?? ''
  }
  const patch = (key: number, changes: Partial<Row>) =>
    setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...changes } : r)))

  function pick(row: Row, instrumentId: string) {
    // the latest close is a starting point; the price actually paid replaces it
    patch(row.key, { instrumentId, price: row.price || priceOf(instrumentId) })
  }

  function split() {
    setRows((rs) =>
      rs.map((r) => {
        const units = wholeUnits(amount, r.weight, r.price || priceOf(r.instrumentId))
        return units === null ? r : { ...r, units: String(units) }
      }),
    )
  }
  const weightTotal = rows.reduce((sum, r) => sum + (Number(r.weight.replace(',', '.')) || 0), 0)
  const canSplit = rows.some((r) => r.instrumentId && r.weight) && amount.trim() !== ''

  const save = useMutation({
    mutationFn: (transactions: TransactionInput[]) =>
      unwrap(api.POST('/api/v1/transactions/batch', { body: { transactions } })),
    onSuccess: async () => {
      await invalidate()
      onDone()
    },
    onError: (error) => {
      if (error instanceof ApiProblem && error.errors.length > 0) {
        setProblems([error.message, ...error.errors.map((e) => e.message)])
      } else {
        setProblems([errorMessage(error)])
      }
    },
  })

  function submit(e: FormEvent) {
    e.preventDefault()
    const found: string[] = []
    if (!accountId) found.push(t('quickAdd.errors.account'))
    const filled = rows.filter((r) => r.instrumentId || r.units || r.price)
    if (filled.length === 0) found.push(t('quickAdd.errors.empty'))
    filled.forEach((r) => {
      const n = rows.indexOf(r) + 1
      if (!r.instrumentId) found.push(t('quickAdd.errors.instrument', { n }))
      if (!/^\d+$/.test(r.units.trim()) || Number(r.units) < 1)
        found.push(t('quickAdd.errors.units', { n }))
      if (!isPositiveDecimal(r.price)) found.push(t('quickAdd.errors.price', { n }))
      if (r.fees.trim() && !/^\d+([.,]\d+)?$/.test(r.fees.trim()))
        found.push(t('quickAdd.errors.fees', { n }))
    })
    setProblems(found)
    if (found.length > 0) return
    save.mutate(
      filled.map((r) => ({
        account_id: Number(accountId),
        type: 'buy' as const,
        trade_date: date,
        instrument_id: Number(r.instrumentId),
        quantity: r.units.trim(),
        price: r.price.trim().replace(',', '.'),
        fees: r.fees.trim().replace(',', '.') || '0',
        taxes: '0',
      })),
    )
  }

  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <p className="text-sm text-muted">{t('quickAdd.intro')}</p>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label={t('quickAdd.account')}>
          {(p) => (
            <Select value={accountId} onChange={(e) => setAccount(e.target.value)} {...p}>
              {accounts.data?.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label={t('quickAdd.date')}>
          {(p) => (
            <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} {...p} />
          )}
        </Field>
        <Field label={t('quickAdd.amount')} hint={t('quickAdd.amountHint')}>
          {(p) => (
            <Input
              inputMode="decimal"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              {...p}
            />
          )}
        </Field>
      </div>

      <fieldset className="space-y-3">
        <legend className="font-medium">{t('quickAdd.rows')}</legend>
        {rows.map((r, i) => (
          <div
            key={r.key}
            role="group"
            aria-label={t('quickAdd.row', { n: i + 1 })}
            className="grid gap-2 sm:grid-cols-[2fr_1fr_1fr_1fr_1fr_auto] sm:items-end"
          >
            <Field label={t('quickAdd.instrument')}>
              {(p) => (
                <Select value={r.instrumentId} onChange={(e) => pick(r, e.target.value)} {...p}>
                  <option value="">{t('quickAdd.choose')}</option>
                  {instruments.data?.map((ins) => (
                    <option key={ins.id} value={ins.id}>
                      {ins.name}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label={t('quickAdd.weight')}>
              {(p) => (
                <Input
                  inputMode="decimal"
                  value={r.weight}
                  onChange={(e) => patch(r.key, { weight: e.target.value })}
                  {...p}
                />
              )}
            </Field>
            <Field label={t('quickAdd.units')}>
              {(p) => (
                <Input
                  inputMode="numeric"
                  value={r.units}
                  onChange={(e) => patch(r.key, { units: e.target.value })}
                  {...p}
                />
              )}
            </Field>
            <Field label={t('quickAdd.price')}>
              {(p) => (
                <Input
                  inputMode="decimal"
                  value={r.price}
                  onChange={(e) => patch(r.key, { price: e.target.value })}
                  {...p}
                />
              )}
            </Field>
            <Field label={t('quickAdd.fees')}>
              {(p) => (
                <Input
                  inputMode="decimal"
                  value={r.fees}
                  onChange={(e) => patch(r.key, { fees: e.target.value })}
                  {...p}
                />
              )}
            </Field>
            <Button
              type="button"
              variant="ghost"
              disabled={rows.length === 1}
              aria-label={t('quickAdd.removeRow', { n: i + 1 })}
              onClick={() => setRows((rs) => rs.filter((x) => x.key !== r.key))}
            >
              ✕
            </Button>
          </div>
        ))}
        <div className="flex flex-wrap items-center gap-2">
          <Button type="button" variant="ghost" onClick={() => setRows((rs) => [...rs, blank()])}>
            {t('quickAdd.addRow')}
          </Button>
          <Button type="button" variant="secondary" disabled={!canSplit} onClick={split}>
            {t('quickAdd.split')}
          </Button>
          {weightTotal > 0 && (
            <span className="text-sm text-muted">
              {t('quickAdd.weightTotal', { total: Math.round(weightTotal * 100) / 100 })}
            </span>
          )}
        </div>
      </fieldset>

      {problems.length > 0 && (
        <Alert>
          {problems.map((message) => (
            <span key={message} className="block">
              {message}
            </span>
          ))}
        </Alert>
      )}
      <Button type="submit" disabled={save.isPending}>
        {t('quickAdd.save')}
      </Button>
    </form>
  )
}
