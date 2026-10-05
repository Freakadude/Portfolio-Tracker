import { useMutation } from '@tanstack/react-query'
import { useMemo, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router-dom'
import { ApiProblem, api, errorMessage, unwrap } from '../api/client'
import { useInvalidateLedger, usePositionDetail, usePrices, type Transaction } from '../api/queries'
import { AsOf, Badge, Dialog, EmptyState, Gain } from '../components/display'
import { HoldingsPanel } from '../lookthrough/HoldingsPanel'
import { PriceAlerts } from '../notify/PriceAlerts'
import { PriceChart } from '../components/PriceChart'
import { TransactionForm } from '../components/TransactionForm'
import { Alert, Button, Card } from '../components/ui'
import { useFormat } from '../lib/useFormat'

function Stat({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="rounded-md border border-border p-3">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="mt-1 text-base font-medium tabular-nums">{children}</dd>
    </div>
  )
}

export function PositionDetail() {
  const { t } = useTranslation()
  const { eur, qty, pct } = useFormat()
  const id = Number(useParams().instrumentId)
  const detail = usePositionDetail(id)
  const prices = usePrices(id)
  const invalidate = useInvalidateLedger()
  const [editing, setEditing] = useState<Transaction | undefined>()
  const remove = useMutation({
    mutationFn: (tx: Transaction) =>
      unwrap(
        api.DELETE('/api/v1/transactions/{transaction_id}', {
          params: { path: { transaction_id: tx.id } },
        }),
      ),
    onSuccess: invalidate,
  })
  function confirmDelete(tx: Transaction) {
    const label = { type: t(`transactions.types.${tx.type}`), date: tx.trade_date }
    if (window.confirm(t('transactions.deleteConfirm', label))) remove.mutate(tx)
  }
  const markers = useMemo(
    () => (detail.data?.transactions ?? []).map((tx) => ({ date: tx.trade_date, type: tx.type })),
    [detail.data],
  )

  if (detail.isPending) return <p role="status">{t('app.loading')}</p>
  if (detail.isError) {
    const missing = detail.error instanceof ApiProblem && detail.error.status === 404
    return (
      <div className="space-y-3">
        <Link to="/holdings" className="text-sm hover:underline">
          ← {t('position.back')}
        </Link>
        {missing ? (
          <EmptyState title={t('holdings.empty.title')} body={detail.error.message} />
        ) : (
          <Alert>{errorMessage(detail.error)}</Alert>
        )}
      </div>
    )
  }

  const d = detail.data
  const s = d.summary
  const held = Number(s.quantity) > 0
  const foreign = d.instrument.currency && d.instrument.currency !== 'EUR'

  return (
    <div className="space-y-6">
      <div>
        <Link to="/holdings" className="text-sm hover:underline">
          ← {t('position.back')}
        </Link>
        <div className="mt-2 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold">{d.instrument.name}</h1>
            <p className="text-sm text-muted">
              {[d.instrument.ticker, d.instrument.isin, t(`assetClass.${d.instrument.asset_class}`)]
                .filter(Boolean)
                .join(' · ')}
            </p>
          </div>
          <div className="flex gap-2">
            <Link
              to={`/transactions?add=buy&instrument=${id}`}
              className="inline-flex min-h-10 items-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground"
            >
              {t('position.buy')}
            </Link>
            {held && (
              <Link
                to={`/transactions?add=sell&instrument=${id}`}
                className="inline-flex min-h-10 items-center rounded-md border border-border px-4 text-sm font-medium"
              >
                {t('position.sell')}
              </Link>
            )}
          </div>
        </div>
      </div>

      <section aria-labelledby="holding-h" className="space-y-3">
        <h2 id="holding-h" className="text-lg font-medium">
          {t('position.holding')}
        </h2>
        {!held && s.cost_basis_eur === '0' && d.lots.length === 0 && (
          <p className="text-muted">{t('position.noPosition')}</p>
        )}
        <dl className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Stat label={t('position.price')}>
            {s.price ? (
              <AsOf date={s.price.date} source={s.price.source}>
                {eur(s.price.close)}
                {s.price.stale && (
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
          </Stat>
          <Stat label={t('position.units')}>{qty(s.quantity)}</Stat>
          <Stat label={t('position.avgCost')}>{s.avg_cost_eur ? eur(s.avg_cost_eur) : '–'}</Stat>
          <Stat label={t('position.costBasis')}>{eur(s.cost_basis_eur)}</Stat>
          <Stat label={t('position.marketValue')}>{eur(s.market_value_eur)}</Stat>
          <Stat label={t('position.unrealized')}>
            <Gain eur={s.unrealized_pnl_eur} ratio={s.unrealized_ratio} />
          </Stat>
          <Stat label={t('position.dayChange')}>
            <Gain eur={s.day_change_eur} ratio={s.day_change_ratio} />
          </Stat>
          <Stat label={t('position.weight')}>{s.weight ? pct(s.weight, 1) : '–'}</Stat>
          <Stat label={t('position.realized')}>{eur(s.realized_pnl_eur)}</Stat>
          <Stat label={t('position.income')}>{eur(s.income_eur)}</Stat>
          <Stat label={t('position.totalReturn')}>
            <Gain eur={s.total_return_eur} ratio={s.total_return_ratio} />
          </Stat>
          <Stat label={t('position.firstPurchase')}>{s.first_trade_date ?? '–'}</Stat>
        </dl>
        {foreign && s.market_value_native && (
          <p className="text-sm text-muted">
            {t('position.native', { currency: d.instrument.currency })}: {s.market_value_native} ·{' '}
            {t('position.costBasis')} {s.cost_basis_native} · {t('position.unrealized')}{' '}
            {s.unrealized_pnl_native}
          </p>
        )}
        {s.note && <Alert>{s.note}</Alert>}
      </section>

      <section aria-labelledby="chart-h" className="space-y-3">
        <h2 id="chart-h" className="text-lg font-medium">
          {t('position.chart')}
        </h2>
        {prices.data && prices.data.length > 0 ? (
          <Card>
            <PriceChart
              prices={prices.data}
              markers={markers}
              label={`${t('position.chart')}: ${d.instrument.name}`}
            />
          </Card>
        ) : (
          !prices.isPending && <p className="text-muted">{t('position.noPrices')}</p>
        )}
      </section>

      <PriceAlerts instrumentId={d.instrument.id} name={d.instrument.name} />

      {['ETF', 'ETC', 'FUND'].includes(d.instrument.asset_class) && (
        <HoldingsPanel instrumentId={d.instrument.id} />
      )}

      {d.lots.length > 0 && (
        <section aria-labelledby="lots-h" className="space-y-2">
          <h2 id="lots-h" className="text-lg font-medium">
            {t('position.lots')}
          </h2>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[40rem] text-sm">
              <caption className="sr-only">{t('position.lotsCaption')}</caption>
              <thead>
                <tr className="border-b border-border">
                  <th scope="col" className="px-3 py-2 text-left font-medium">
                    {t('position.lotColumns.date')}
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    {t('position.lotColumns.units')}
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    {t('position.lotColumns.cost')}
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    {t('position.lotColumns.avg')}
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    {t('position.lotColumns.value')}
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    {t('position.lotColumns.result')}
                  </th>
                </tr>
              </thead>
              <tbody>
                {d.lots.map((lot) => (
                  <tr
                    key={`${lot.account_id}-${lot.buy_transaction_id}`}
                    className="border-b border-border"
                  >
                    <td className="px-3 py-2">{lot.trade_date}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{qty(lot.open_quantity)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{eur(lot.cost_eur)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{eur(lot.avg_cost_eur)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {eur(lot.market_value_eur)}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <Gain eur={lot.unrealized_pnl_eur} ratio={lot.unrealized_ratio} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {d.matches.length > 0 && (
        <section aria-labelledby="matches-h" className="space-y-2">
          <h2 id="matches-h" className="text-lg font-medium">
            {t('position.matches')}
          </h2>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[36rem] text-sm">
              <thead>
                <tr className="border-b border-border">
                  <th scope="col" className="px-3 py-2 text-left font-medium">
                    {t('position.matchColumns.sold')}
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    {t('position.matchColumns.units')}
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    {t('position.matchColumns.cost')}
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    {t('position.matchColumns.proceeds')}
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    {t('position.matchColumns.result')}
                  </th>
                </tr>
              </thead>
              <tbody>
                {d.matches.map((m, i) => (
                  <tr
                    key={`${m.sell_transaction_id}-${m.lot_buy_transaction_id}-${i}`}
                    className="border-b border-border"
                  >
                    <td className="px-3 py-2">{m.sell_date ?? '–'}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{qty(m.quantity)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{eur(m.cost_eur)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{eur(m.proceeds_eur)}</td>
                    <td className="px-3 py-2 text-right">
                      <Gain eur={m.realized_pnl_eur} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {d.transactions.length > 0 && (
        <section aria-labelledby="history-h" className="space-y-2">
          <h2 id="history-h" className="text-lg font-medium">
            {t('position.history')}
          </h2>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[36rem] text-sm">
              <thead>
                <tr className="border-b border-border">
                  <th scope="col" className="px-3 py-2 text-left font-medium">
                    {t('position.historyColumns.date')}
                  </th>
                  <th scope="col" className="px-3 py-2 text-left font-medium">
                    {t('position.historyColumns.type')}
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    {t('position.historyColumns.units')}
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    {t('position.historyColumns.price')}
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    {t('position.historyColumns.amount')}
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    <span className="sr-only">{t('position.historyColumns.actions')}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {d.transactions.map((tx) => (
                  <tr key={tx.id} className="border-b border-border">
                    <td className="px-3 py-2">{tx.trade_date}</td>
                    <td className="px-3 py-2">{t(`transactions.types.${tx.type}`)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {Number(tx.quantity) ? qty(tx.quantity) : '–'}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {Number(tx.price) ? `${tx.price} ${tx.currency}` : '–'}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {tx.net_amount_eur ? eur(tx.net_amount_eur) : '–'}
                    </td>
                    <td className="px-3 py-2 text-right whitespace-nowrap">
                      <Button
                        variant="ghost"
                        onClick={() => setEditing(tx)}
                        aria-label={t('position.editRow', {
                          type: t(`transactions.types.${tx.type}`),
                          date: tx.trade_date,
                        })}
                      >
                        {t('transactions.edit')}
                      </Button>
                      <Button
                        variant="ghost"
                        onClick={() => confirmDelete(tx)}
                        aria-label={t('position.deleteRow', {
                          type: t(`transactions.types.${tx.type}`),
                          date: tx.trade_date,
                        })}
                      >
                        {t('transactions.delete')}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {remove.isError && <Alert>{errorMessage(remove.error)}</Alert>}
      <Dialog
        open={Boolean(editing)}
        onClose={() => setEditing(undefined)}
        title={t('txForm.editTitle')}
        wide
      >
        <TransactionForm editing={editing} onDone={() => setEditing(undefined)} />
      </Dialog>
    </div>
  )
}
