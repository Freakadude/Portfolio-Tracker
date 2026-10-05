import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router-dom'
import { api, errorMessage, unwrap } from '../api/client'
import { useAccounts, useInstruments } from '../api/queries'
import { EmptyState } from '../components/display'
import { Alert, Button, Field, Input, Select } from '../components/ui'
import { isPositiveDecimal } from '../lib/decimal'
import { useFormat } from '../lib/useFormat'

const GROUPINGS = ['asset_class', 'sleeve', 'region', 'sector', 'currency', 'instrument'] as const
type Grouping = (typeof GROUPINGS)[number]

interface Row {
  key: number
  instrumentId: string
  side: 'buy' | 'sell'
  quantity: string
  price: string
  fees: string
}

let nextKey = 1
const blank = (): Row => ({
  key: nextKey++,
  instrumentId: '',
  side: 'buy',
  quantity: '',
  price: '',
  fees: '',
})

/** `?proposal=` carries a list of trades to try, as JSON: [{"instrument_id":1,"side":"buy","quantity":"3"}].
 * A malformed value is ignored rather than breaking the page. */
export function parseProposal(text: string | null): Row[] {
  if (!text) return []
  try {
    const parsed: unknown = JSON.parse(text)
    if (!Array.isArray(parsed)) return []
    const rows: Row[] = []
    for (const item of parsed) {
      if (typeof item !== 'object' || item === null) continue
      const r = item as Record<string, unknown>
      const id = Number(r.instrument_id)
      if (!Number.isInteger(id) || id <= 0) continue
      rows.push({
        key: nextKey++,
        instrumentId: String(id),
        side: r.side === 'sell' ? 'sell' : 'buy',
        quantity: r.quantity == null ? '' : String(r.quantity),
        price: r.price_eur == null ? '' : String(r.price_eur),
        fees: r.fees_eur == null ? '' : String(r.fees_eur),
      })
    }
    return rows
  } catch {
    return []
  }
}

/** Try trades before making them: the allocation, drift and cash need afterwards. Nothing is
 * saved (FR-PF-09). */
export function WhatIf() {
  const { t } = useTranslation()
  const { eur, num, qty, pct } = useFormat()
  const [params] = useSearchParams()
  const instruments = useInstruments()
  const accounts = useAccounts()
  const [rows, setRows] = useState<Row[]>(() => {
    const proposed = parseProposal(params.get('proposal'))
    return proposed.length > 0 ? proposed : [blank()]
  })
  const [groupBy, setGroupBy] = useState<Grouping>('asset_class')
  const [account, setAccount] = useState('')
  const [errors, setErrors] = useState<string[]>([])

  const run = useMutation({
    mutationFn: (body: {
      trades: {
        instrument_id: number
        side: 'buy' | 'sell'
        quantity: string
        price_eur?: string
        fees_eur: string
      }[]
    }) =>
      unwrap(
        api.POST('/api/v1/portfolio/simulate', {
          body: { ...body, group_by: groupBy, account: account ? Number(account) : null },
        }),
      ),
  })

  const patch = (key: number, changes: Partial<Row>) =>
    setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...changes } : r)))

  function submit(e: React.FormEvent) {
    e.preventDefault()
    const problems: string[] = []
    const trades = rows.map((r, i) => {
      const n = i + 1
      if (!r.instrumentId) problems.push(t('whatIf.errors.instrument', { n }))
      if (!isPositiveDecimal(r.quantity)) problems.push(t('whatIf.errors.quantity', { n }))
      if (r.price.trim() && !isPositiveDecimal(r.price))
        problems.push(t('whatIf.errors.price', { n }))
      if (r.fees.trim() && !isPositiveDecimal(r.fees) && r.fees.trim() !== '0')
        problems.push(t('whatIf.errors.fees', { n }))
      return {
        instrument_id: Number(r.instrumentId),
        side: r.side,
        quantity: r.quantity.trim(),
        ...(r.price.trim() ? { price_eur: r.price.trim() } : {}),
        fees_eur: r.fees.trim() || '0',
      }
    })
    setErrors(problems)
    if (problems.length === 0) run.mutate({ trades })
  }

  const result = run.data
  const noInstruments = instruments.isSuccess && instruments.data.length === 0

  return (
    <div className="space-y-6">
      <div>
        <Link to="/holdings" className="text-sm hover:underline">
          ← {t('whatIf.back')}
        </Link>
        <h1 className="mt-2 text-2xl font-semibold">{t('whatIf.title')}</h1>
        <p className="max-w-2xl text-muted">{t('whatIf.intro')}</p>
      </div>

      {noInstruments ? (
        <EmptyState title={t('whatIf.empty.title')} body={t('whatIf.empty.body')} />
      ) : (
        <form onSubmit={submit} className="space-y-4" noValidate>
          <div className="flex flex-wrap gap-4">
            <Field label={t('whatIf.groupBy')}>
              {(p) => (
                <Select
                  value={groupBy}
                  onChange={(e) => setGroupBy(e.target.value as Grouping)}
                  {...p}
                >
                  {GROUPINGS.map((g) => (
                    <option key={g} value={g}>
                      {t(`widgets.groups.${g}`, { defaultValue: g })}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label={t('whatIf.account')}>
              {(p) => (
                <Select value={account} onChange={(e) => setAccount(e.target.value)} {...p}>
                  <option value="">{t('holdings.allAccounts')}</option>
                  {accounts.data?.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
          </div>

          <fieldset className="space-y-3">
            <legend className="font-medium">{t('whatIf.trades')}</legend>
            {rows.map((r, i) => (
              <div
                key={r.key}
                role="group"
                aria-label={t('whatIf.row', { n: i + 1 })}
                className="grid gap-2 sm:grid-cols-[2fr_1fr_1fr_1fr_1fr_auto] sm:items-end"
              >
                <Field label={t('whatIf.instrument')}>
                  {(p) => (
                    <Select
                      value={r.instrumentId}
                      onChange={(e) => patch(r.key, { instrumentId: e.target.value })}
                      {...p}
                    >
                      <option value="">{t('whatIf.choose')}</option>
                      {instruments.data?.map((ins) => (
                        <option key={ins.id} value={ins.id}>
                          {ins.name}
                        </option>
                      ))}
                    </Select>
                  )}
                </Field>
                <Field label={t('whatIf.side')}>
                  {(p) => (
                    <Select
                      value={r.side}
                      onChange={(e) => patch(r.key, { side: e.target.value as 'buy' | 'sell' })}
                      {...p}
                    >
                      <option value="buy">{t('whatIf.buy')}</option>
                      <option value="sell">{t('whatIf.sell')}</option>
                    </Select>
                  )}
                </Field>
                <Field label={t('whatIf.quantity')}>
                  {(p) => (
                    <Input
                      inputMode="decimal"
                      value={r.quantity}
                      onChange={(e) => patch(r.key, { quantity: e.target.value })}
                      {...p}
                    />
                  )}
                </Field>
                <Field label={t('whatIf.price')}>
                  {(p) => (
                    <Input
                      inputMode="decimal"
                      placeholder={t('whatIf.latest')}
                      value={r.price}
                      onChange={(e) => patch(r.key, { price: e.target.value })}
                      {...p}
                    />
                  )}
                </Field>
                <Field label={t('whatIf.fees')}>
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
                  aria-label={t('whatIf.removeRow', { n: i + 1 })}
                  onClick={() => setRows((rs) => rs.filter((x) => x.key !== r.key))}
                >
                  ✕
                </Button>
              </div>
            ))}
            <Button type="button" variant="ghost" onClick={() => setRows((rs) => [...rs, blank()])}>
              {t('whatIf.addRow')}
            </Button>
          </fieldset>

          {errors.length > 0 && (
            <Alert>
              {errors.map((message) => (
                <span key={message} className="block">
                  {message}
                </span>
              ))}
            </Alert>
          )}
          {run.isError && <Alert>{errorMessage(run.error)}</Alert>}
          <Button type="submit" disabled={run.isPending}>
            {t('whatIf.run')}
          </Button>
        </form>
      )}

      {result && (
        <section aria-label={t('whatIf.result')} className="space-y-6">
          <p className="text-lg" role="status">
            {Number(result.cash_needed_eur) >= 0
              ? t('whatIf.cashNeeded', { amount: eur(result.cash_needed_eur) })
              : t('whatIf.cashFreed', { amount: eur(Math.abs(Number(result.cash_needed_eur))) })}
          </p>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <caption className="mb-1 text-left font-medium">{t('whatIf.positions')}</caption>
              <thead>
                <tr className="border-b border-border text-left">
                  <th scope="col" className="py-2 pr-3 font-medium">
                    {t('whatIf.instrument')}
                  </th>
                  <th scope="col" className="py-2 pr-3 text-right font-medium">
                    {t('whatIf.unitsBefore')}
                  </th>
                  <th scope="col" className="py-2 pr-3 text-right font-medium">
                    {t('whatIf.unitsAfter')}
                  </th>
                  <th scope="col" className="py-2 pr-3 text-right font-medium">
                    {t('whatIf.valueBefore')}
                  </th>
                  <th scope="col" className="py-2 text-right font-medium">
                    {t('whatIf.valueAfter')}
                  </th>
                </tr>
              </thead>
              <tbody>
                {result.positions.map((p) => (
                  <tr key={p.instrument_id} className="border-b border-border">
                    <td className="py-2 pr-3">{p.name}</td>
                    <td className="py-2 pr-3 text-right tabular-nums">{qty(p.quantity_before)}</td>
                    <td className="py-2 pr-3 text-right tabular-nums">{qty(p.quantity_after)}</td>
                    <td className="py-2 pr-3 text-right tabular-nums">{eur(p.value_before_eur)}</td>
                    <td className="py-2 text-right tabular-nums">{eur(p.value_after_eur)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <AllocationCompare
            title={t('whatIf.allocation', {
              group: t(`widgets.groups.${groupBy}`, { defaultValue: groupBy }),
            })}
            before={result.before.slices}
            after={result.after.slices}
            pct={(v) => pct(v, 1)}
            pp={(v) => `${num(Number(v) * 100, 1)} pp`}
          />
        </section>
      )}
    </div>
  )
}

type Slice = {
  key: string
  weight: string
  target: string | null
  drift_pp: string | null
  outside_band: boolean | null
}

function AllocationCompare({
  title,
  before,
  after,
  pct,
  pp,
}: {
  title: string
  before: Slice[]
  after: Slice[]
  pct: (v: string) => string
  pp: (v: string) => string
}) {
  const { t } = useTranslation()
  const keys = [...new Set([...before.map((s) => s.key), ...after.map((s) => s.key)])]
  const b = new Map(before.map((s) => [s.key, s]))
  const a = new Map(after.map((s) => [s.key, s]))
  const hasTargets = [...before, ...after].some((s) => s.target !== null)
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <caption className="mb-1 text-left font-medium">{title}</caption>
        <thead>
          <tr className="border-b border-border text-left">
            <th scope="col" className="py-2 pr-3 font-medium">
              {t('whatIf.group')}
            </th>
            <th scope="col" className="py-2 pr-3 text-right font-medium">
              {t('whatIf.before')}
            </th>
            <th scope="col" className="py-2 pr-3 text-right font-medium">
              {t('whatIf.after')}
            </th>
            {hasTargets && (
              <>
                <th scope="col" className="py-2 pr-3 text-right font-medium">
                  {t('whatIf.target')}
                </th>
                <th scope="col" className="py-2 pr-3 text-right font-medium">
                  {t('whatIf.driftBefore')}
                </th>
                <th scope="col" className="py-2 text-right font-medium">
                  {t('whatIf.driftAfter')}
                </th>
              </>
            )}
          </tr>
        </thead>
        <tbody>
          {keys.map((k) => {
            const sb = b.get(k)
            const sa = a.get(k)
            const target = sa?.target ?? sb?.target ?? null
            return (
              <tr key={k} className="border-b border-border">
                <td className="py-2 pr-3">{k}</td>
                <td className="py-2 pr-3 text-right tabular-nums">{pct(sb?.weight ?? '0')}</td>
                <td className="py-2 pr-3 text-right tabular-nums">{pct(sa?.weight ?? '0')}</td>
                {hasTargets && (
                  <>
                    <td className="py-2 pr-3 text-right tabular-nums">
                      {target === null ? '–' : pct(target)}
                    </td>
                    <td className="py-2 pr-3 text-right tabular-nums">
                      {sb?.drift_pp == null ? '–' : pp(sb.drift_pp)}
                    </td>
                    <td className="py-2 text-right tabular-nums">
                      {sa?.drift_pp == null ? '–' : pp(sa.drift_pp)}
                      {sa?.outside_band && (
                        <span className="ml-1 text-danger">{t('whatIf.outsideBand')}</span>
                      )}
                    </td>
                  </>
                )}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
