import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router-dom'
import { api, errorMessage, unwrap } from '../api/client'
import {
  useAccounts,
  useDrafts,
  useInstruments,
  useInvalidateLedger,
  useTransactions,
  type Transaction,
  type TransactionFilters,
} from '../api/queries'
import { Badge, Dialog, EmptyState } from '../components/display'
import { QuickAdd } from '../components/QuickAdd'
import { Reconcile } from '../components/Reconcile'
import { TransactionForm, TYPES, type TxType } from '../components/TransactionForm'
import { Alert, Button, Field, Input, Select } from '../components/ui'
import { useFormat } from '../lib/useFormat'

export function Transactions() {
  const { t } = useTranslation()
  const { eur, num, qty } = useFormat()
  const [params, setParams] = useSearchParams()
  const accounts = useAccounts()
  const instruments = useInstruments('all')
  const drafts = useDrafts()
  const invalidate = useInvalidateLedger()

  const [filters, setFilters] = useState<TransactionFilters>(() => ({
    account: params.get('account') ? Number(params.get('account')) : undefined,
    // with ?add= the instrument is the one to prefill the form with, not a filter
    instrument:
      params.get('instrument') && !params.has('add') ? Number(params.get('instrument')) : undefined,
    type: params.get('type') ?? undefined,
    from: params.get('from') ?? undefined,
    to: params.get('to') ?? undefined,
  }))
  const list = useTransactions(filters)
  const [editing, setEditing] = useState<Transaction | undefined>()
  const [adding, setAdding] = useState(() => params.has('add'))
  const [quick, setQuick] = useState(false)
  const [reconciling, setReconciling] = useState(false)
  const [initial] = useState(() => {
    const type = params.get('add')
    return {
      type: (TYPES as readonly string[]).includes(type ?? '') ? (type as TxType) : undefined,
      instrumentId: params.get('instrument') ?? undefined,
    }
  })

  const remove = useMutation({
    mutationFn: (tx: Transaction) =>
      unwrap(
        api.DELETE('/api/v1/transactions/{transaction_id}', {
          params: { path: { transaction_id: tx.id } },
        }),
      ),
    onSuccess: invalidate,
  })

  function closeForm() {
    setAdding(false)
    setEditing(undefined)
    if (params.has('add')) setParams({}, { replace: true })
  }

  function confirmDelete(tx: Transaction) {
    const ok = window.confirm(
      t('transactions.deleteConfirm', {
        type: t(`transactions.types.${tx.type}`),
        date: tx.trade_date,
      }),
    )
    if (ok) remove.mutate(tx)
  }

  const rows = list.data?.pages.flatMap((p) => p.items) ?? []
  const filtered = Object.values(filters).some(Boolean)
  const draftCount = drafts.data?.items.length ?? 0
  const set = (key: keyof TransactionFilters, value: string) =>
    setFilters((f) => ({
      ...f,
      [key]: value
        ? key === 'account' || key === 'instrument'
          ? Number(value)
          : value
        : undefined,
    }))

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-semibold">{t('transactions.title')}</h1>
        <div className="flex gap-2">
          <Link
            to="/transactions/import"
            className="rounded-md border border-border px-3 py-2 text-sm hover:bg-border/40"
          >
            {t('transactions.import')}
          </Link>
          <Button
            variant="secondary"
            onClick={() => setReconciling(true)}
            title={t('reconcile.hover')}
          >
            {t('reconcile.open')}
          </Button>
          <Button variant="secondary" onClick={() => setQuick(true)}>
            {t('quickAdd.title')}
          </Button>
          <Button onClick={() => setAdding(true)}>{t('transactions.add')}</Button>
        </div>
      </div>

      {draftCount > 0 && (
        <Alert>
          <Link to="/insights" className="underline">
            {t('transactions.drafts', { count: draftCount })}
          </Link>
        </Alert>
      )}

      <form
        className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6"
        aria-label={t('transactions.title')}
      >
        <Field label={t('transactions.filters.account')}>
          {(p) => (
            <Select
              value={filters.account ?? ''}
              onChange={(e) => set('account', e.target.value)}
              {...p}
            >
              <option value="">{t('transactions.filters.all')}</option>
              {accounts.data?.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label={t('transactions.filters.instrument')}>
          {(p) => (
            <Select
              value={filters.instrument ?? ''}
              onChange={(e) => set('instrument', e.target.value)}
              {...p}
            >
              <option value="">{t('transactions.filters.all')}</option>
              {instruments.data?.map((i) => (
                <option key={i.id} value={i.id}>
                  {i.name}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label={t('transactions.filters.type')}>
          {(p) => (
            <Select value={filters.type ?? ''} onChange={(e) => set('type', e.target.value)} {...p}>
              <option value="">{t('transactions.filters.all')}</option>
              {TYPES.map((x) => (
                <option key={x} value={x}>
                  {t(`transactions.types.${x}`)}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label={t('transactions.filters.from')}>
          {(p) => (
            <Input
              type="date"
              value={filters.from ?? ''}
              onChange={(e) => set('from', e.target.value)}
              {...p}
            />
          )}
        </Field>
        <Field label={t('transactions.filters.to')}>
          {(p) => (
            <Input
              type="date"
              value={filters.to ?? ''}
              onChange={(e) => set('to', e.target.value)}
              {...p}
            />
          )}
        </Field>
        {filtered && (
          <div className="flex items-end">
            <Button type="button" variant="ghost" onClick={() => setFilters({})}>
              {t('transactions.filters.clear')}
            </Button>
          </div>
        )}
      </form>

      {list.isError && <Alert>{errorMessage(list.error)}</Alert>}
      {remove.isError && <Alert>{errorMessage(remove.error)}</Alert>}

      {list.isSuccess && rows.length === 0 ? (
        <EmptyState
          title={filtered ? t('transactions.empty.noMatch') : t('transactions.empty.title')}
          body={filtered ? '' : t('transactions.empty.body')}
          action={
            !filtered && <Button onClick={() => setAdding(true)}>{t('transactions.add')}</Button>
          }
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <caption className="sr-only">{t('transactions.caption')}</caption>
            <thead>
              <tr className="border-b border-border text-left">
                <th scope="col" className="py-2 pr-3 font-medium">
                  {t('transactions.columns.date')}
                </th>
                <th scope="col" className="py-2 pr-3 font-medium">
                  {t('transactions.columns.type')}
                </th>
                <th scope="col" className="py-2 pr-3 font-medium">
                  {t('transactions.columns.instrument')}
                </th>
                <th scope="col" className="py-2 pr-3 font-medium">
                  {t('transactions.columns.account')}
                </th>
                <th scope="col" className="py-2 pr-3 text-right font-medium">
                  {t('transactions.columns.units')}
                </th>
                <th scope="col" className="py-2 pr-3 text-right font-medium">
                  {t('transactions.columns.price')}
                </th>
                <th scope="col" className="py-2 pr-3 text-right font-medium">
                  {t('transactions.columns.fees')}
                </th>
                <th scope="col" className="py-2 pr-3 text-right font-medium">
                  {t('transactions.columns.amount')}
                </th>
                <th scope="col" className="py-2 pr-3 font-medium">
                  {t('transactions.columns.source')}
                </th>
                <th scope="col" className="py-2 font-medium">
                  {t('transactions.columns.actions')}
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((tx) => {
                const trade = tx.type === 'buy' || tx.type === 'sell'
                return (
                  <tr key={tx.id} className="border-b border-border align-top">
                    <td className="py-2 pr-3 whitespace-nowrap">{tx.trade_date}</td>
                    <td className="py-2 pr-3">{t(`transactions.types.${tx.type}`)}</td>
                    <td className="py-2 pr-3">{tx.instrument_name ?? '–'}</td>
                    <td className="py-2 pr-3">{tx.account_name}</td>
                    <td className="py-2 pr-3 text-right tabular-nums">
                      {Number(tx.quantity) ? qty(tx.quantity) : '–'}
                    </td>
                    <td className="py-2 pr-3 text-right tabular-nums">
                      {trade ? `${num(tx.price, 4)} ${tx.currency}` : '–'}
                    </td>
                    <td className="py-2 pr-3 text-right tabular-nums">
                      {Number(tx.fees) ? eur(tx.fees) : '–'}
                    </td>
                    <td className="py-2 pr-3 text-right tabular-nums">
                      {tx.net_amount_eur ? eur(tx.net_amount_eur) : '–'}
                    </td>
                    <td className="py-2 pr-3">
                      <Badge tone={tx.source === 'corporate_action' ? 'warn' : 'neutral'}>
                        {t(`transactions.sources.${tx.source}`, { defaultValue: tx.source })}
                      </Badge>
                    </td>
                    <td className="py-2 whitespace-nowrap">
                      <Button variant="ghost" onClick={() => setEditing(tx)}>
                        {t('transactions.edit')}
                      </Button>
                      <Button variant="ghost" onClick={() => confirmDelete(tx)}>
                        {t('transactions.delete')}
                      </Button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          {list.hasNextPage && (
            <div className="pt-3">
              <Button
                variant="secondary"
                onClick={() => void list.fetchNextPage()}
                disabled={list.isFetchingNextPage}
              >
                {t('app.more')}
              </Button>
            </div>
          )}
        </div>
      )}

      <Dialog
        open={adding || Boolean(editing)}
        onClose={closeForm}
        title={t(editing ? 'txForm.editTitle' : 'txForm.addTitle')}
        wide
      >
        <TransactionForm editing={editing} initial={initial} onDone={closeForm} />
      </Dialog>
      <QuickAdd open={quick} onClose={() => setQuick(false)} />
      <Reconcile open={reconciling} onClose={() => setReconciling(false)} />
    </div>
  )
}
