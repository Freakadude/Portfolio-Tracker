import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, errorMessage, unwrap } from '../api/client'
import { useDrafts, useInvalidateLedger, type Transaction } from '../api/queries'
import { Panel } from '../components/Panel'
import { Alert, Button, Input } from '../components/ui'
import { trimDecimal } from '../lib/decimal'
import { useFormat } from '../lib/useFormat'

/** Buys and sells a strategy calculator proposed (FR-ST-05): set the price and fees you
 * actually paid, then confirm each one; nothing changes in the ledger before that. */
export function OrderDrafts() {
  const { t } = useTranslation()
  const drafts = useDrafts()
  const rows = drafts.data?.items.filter((x) => x.type === 'buy' || x.type === 'sell') ?? []
  if (drafts.isSuccess && rows.length === 0) return null
  return (
    <Panel id="insights-orders" title={t('strategies.orders.title')} count={rows.length}>
      <p className="text-sm text-muted">{t('strategies.orders.intro')}</p>
      {drafts.isError && <Alert>{errorMessage(drafts.error)}</Alert>}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <caption className="sr-only">{t('strategies.orders.title')}</caption>
          <thead>
            <tr className="border-b border-border text-left">
              {(
                [
                  'date',
                  'side',
                  'instrument',
                  'account',
                  'units',
                  'price',
                  'fees',
                  'actions',
                ] as const
              ).map((c) => (
                <th key={c} scope="col" className="py-2 pr-3 font-medium">
                  {t(`strategies.orders.columns.${c}`)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((d) => (
              <OrderRow key={d.id} draft={d} />
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  )
}

function OrderRow({ draft }: { draft: Transaction }) {
  const { t } = useTranslation()
  const { qty } = useFormat()
  const invalidate = useInvalidateLedger()
  const originalPrice = trimDecimal(draft.price ?? '0')
  const [price, setPrice] = useState(originalPrice)
  const [fees, setFees] = useState('')
  const name = draft.instrument_name ?? ''
  const confirm = useMutation({
    mutationFn: () => {
      const changes: { price?: string; fees?: string } = {}
      if (price.trim() !== originalPrice) changes.price = price.trim().replace(',', '.')
      if (fees.trim()) changes.fees = fees.trim().replace(',', '.')
      return unwrap(
        api.POST('/api/v1/transactions/{transaction_id}/confirm', {
          params: { path: { transaction_id: draft.id } },
          body: Object.keys(changes).length ? changes : null,
        }),
      )
    },
    onSuccess: invalidate,
  })
  const remove = useMutation({
    mutationFn: () =>
      unwrap(
        api.DELETE('/api/v1/transactions/{transaction_id}', {
          params: { path: { transaction_id: draft.id } },
        }),
      ),
    onSuccess: invalidate,
  })
  const error = confirm.error ?? remove.error
  return (
    <tr className="border-b border-border align-top">
      <td className="py-2 pr-3 whitespace-nowrap">{draft.trade_date}</td>
      <td className="py-2 pr-3">{t(`transactions.types.${draft.type}`)}</td>
      <td className="py-2 pr-3">{name}</td>
      <td className="py-2 pr-3">{draft.account_name}</td>
      <td className="py-2 pr-3 tabular-nums">{qty(draft.quantity)}</td>
      <td className="py-2 pr-3">
        <Input
          className="w-28"
          inputMode="decimal"
          aria-label={t('strategies.orders.priceFor', { name })}
          value={price}
          onChange={(e) => setPrice(e.target.value)}
        />
      </td>
      <td className="py-2 pr-3">
        <Input
          className="w-24"
          inputMode="decimal"
          aria-label={t('strategies.orders.feesFor', { name })}
          value={fees}
          onChange={(e) => setFees(e.target.value)}
        />
        {error && (
          <p role="alert" className="text-sm text-danger">
            {errorMessage(error)}
          </p>
        )}
      </td>
      <td className="py-2 whitespace-nowrap">
        <Button
          onClick={() => confirm.mutate()}
          disabled={confirm.isPending}
          aria-label={t('strategies.orders.confirmFor', { name })}
        >
          {t('strategies.orders.confirm')}
        </Button>{' '}
        <Button
          variant="secondary"
          onClick={() => remove.mutate()}
          disabled={remove.isPending}
          aria-label={t('strategies.orders.dropFor', { name })}
        >
          {t('strategies.orders.drop')}
        </Button>
      </td>
    </tr>
  )
}
