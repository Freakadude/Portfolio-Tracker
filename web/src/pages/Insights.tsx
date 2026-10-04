import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, errorMessage, unwrap } from '../api/client'
import {
  useCorporateActions,
  useDrafts,
  useInvalidateLedger,
  type CorporateAction,
  type Transaction,
} from '../api/queries'
import { Alert, Button, Input } from '../components/ui'
import { trimDecimal } from '../lib/decimal'
import { useFormat } from '../lib/useFormat'

export function Insights() {
  const { t } = useTranslation()
  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-semibold">{t('insights.title')}</h1>
      <Splits />
      <Dividends />
    </div>
  )
}

function Splits() {
  const { t } = useTranslation()
  const { eur, qty } = useFormat()
  const invalidate = useInvalidateLedger()
  const actions = useCorporateActions('proposed')
  const act = useMutation({
    mutationFn: ({ id, verb }: { id: number; verb: 'confirm' | 'dismiss' }) =>
      unwrap(
        api.POST(`/api/v1/corporate-actions/{action_id}/${verb}`, {
          params: { path: { action_id: id } },
        }),
      ),
    onSuccess: invalidate,
  })
  const rows = actions.data ?? []
  return (
    <section className="space-y-2" aria-labelledby="splits-title">
      <h2 id="splits-title" className="text-lg font-semibold">
        {t('insights.splits.title')}
      </h2>
      {act.isError && <Alert>{errorMessage(act.error)}</Alert>}
      {actions.isError && <Alert>{errorMessage(actions.error)}</Alert>}
      {actions.isSuccess && rows.length === 0 ? (
        <p className="text-muted">{t('insights.splits.empty')}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <caption className="sr-only">{t('insights.splits.caption')}</caption>
            <thead>
              <tr className="border-b border-border text-left">
                {(['instrument', 'exDate', 'ratio', 'effect', 'actions'] as const).map((c) => (
                  <th key={c} scope="col" className="py-2 pr-3 font-medium">
                    {t(`insights.splits.columns.${c}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((a: CorporateAction) => (
                <tr key={a.id} className="border-b border-border align-top">
                  <td className="py-2 pr-3">{a.instrument_name}</td>
                  <td className="py-2 pr-3 whitespace-nowrap">{a.ex_date}</td>
                  <td className="py-2 pr-3">
                    {a.ratio ? t('insights.splits.ratio', { ratio: trimDecimal(a.ratio) }) : '–'}
                  </td>
                  <td className="py-2 pr-3">
                    <ul className="space-y-1">
                      {a.effects.map((e) => (
                        <li key={e.account_id}>
                          {t('insights.splits.effect', {
                            account: e.account_name,
                            before: qty(e.quantity_before),
                            after: qty(e.quantity_after),
                            cost: eur(e.cost_basis_eur),
                          })}
                        </li>
                      ))}
                    </ul>
                  </td>
                  <td className="py-2 whitespace-nowrap">
                    <Button
                      onClick={() => act.mutate({ id: a.id, verb: 'confirm' })}
                      disabled={act.isPending}
                      aria-label={`${t('insights.splits.confirm')} ${a.instrument_name}`}
                    >
                      {t('insights.splits.confirm')}
                    </Button>{' '}
                    <Button
                      variant="secondary"
                      onClick={() => act.mutate({ id: a.id, verb: 'dismiss' })}
                      disabled={act.isPending}
                      aria-label={`${t('insights.splits.dismiss')} ${a.instrument_name}`}
                    >
                      {t('insights.splits.dismiss')}
                    </Button>
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

function Dividends() {
  const { t } = useTranslation()
  const drafts = useDrafts()
  const rows = drafts.data?.items.filter((x) => x.type === 'dividend') ?? []
  return (
    <section className="space-y-2" aria-labelledby="dividends-title">
      <h2 id="dividends-title" className="text-lg font-semibold">
        {t('insights.dividends.title')}
      </h2>
      <p className="text-sm text-muted">{t('insights.dividends.intro')}</p>
      {drafts.isError && <Alert>{errorMessage(drafts.error)}</Alert>}
      {drafts.isSuccess && rows.length === 0 ? (
        <p className="text-muted">{t('insights.dividends.empty')}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <caption className="sr-only">{t('insights.dividends.caption')}</caption>
            <thead>
              <tr className="border-b border-border text-left">
                {(['date', 'instrument', 'account', 'units', 'amount', 'actions'] as const).map(
                  (c) => (
                    <th key={c} scope="col" className="py-2 pr-3 font-medium">
                      {t(`insights.dividends.columns.${c}`)}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {rows.map((d) => (
                <DraftRow key={d.id} draft={d} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function DraftRow({ draft }: { draft: Transaction }) {
  const { t } = useTranslation()
  const { qty } = useFormat()
  const invalidate = useInvalidateLedger()
  const original = trimDecimal(draft.net_amount_eur ?? '0')
  const [amount, setAmount] = useState(original)
  const name = draft.instrument_name ?? ''

  const confirm = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST('/api/v1/transactions/{transaction_id}/confirm', {
          params: { path: { transaction_id: draft.id } },
          body: amount.trim() !== original ? { net_amount_eur: amount.trim() } : null,
        }),
      ),
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
      <td className="py-2 pr-3">{name}</td>
      <td className="py-2 pr-3">{draft.account_name}</td>
      <td className="py-2 pr-3 text-right tabular-nums">{qty(draft.quantity)}</td>
      <td className="py-2 pr-3">
        <Input
          value={amount}
          inputMode="decimal"
          aria-label={t('insights.dividends.amountFor', { name })}
          onChange={(e) => setAmount(e.target.value)}
          className="w-32"
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
          aria-label={`${t('insights.dividends.confirm')} ${name}`}
        >
          {t('insights.dividends.confirm')}
        </Button>{' '}
        <Button
          variant="secondary"
          onClick={() => {
            if (
              window.confirm(
                t('insights.dividends.deleteConfirm', { name, date: draft.trade_date }),
              )
            )
              remove.mutate()
          }}
          disabled={remove.isPending}
          aria-label={`${t('insights.dividends.delete')} ${name}`}
        >
          {t('insights.dividends.delete')}
        </Button>
      </td>
    </tr>
  )
}
