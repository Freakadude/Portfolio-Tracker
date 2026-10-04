import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { errorMessage } from '../api/client'
import { useAccounts, useInstruments, usePositions, type Position } from '../api/queries'
import { AddInstrumentDialog } from '../components/AddInstrumentDialog'
import { AsOf, Badge, EmptyState, Gain, SortHeader, useSort } from '../components/display'
import { InstrumentsTab } from '../components/InstrumentsTab'
import { Alert, Button, Checkbox, Select } from '../components/ui'
import { cn } from '../lib/cn'
import { toNumber } from '../lib/format'
import { useFormat } from '../lib/useFormat'

type Tab = 'positions' | 'instruments'
type SortKey =
  | 'name'
  | 'account'
  | 'quantity'
  | 'avgCost'
  | 'cost'
  | 'price'
  | 'value'
  | 'unrealized'
  | 'day'
  | 'weight'

const ACCESSORS: Record<SortKey, (p: Position) => string | number | null> = {
  name: (p) => p.name.toLowerCase(),
  account: (p) => p.account_name.toLowerCase(),
  quantity: (p) => toNumber(p.quantity),
  avgCost: (p) => toNumber(p.avg_cost_eur),
  cost: (p) => toNumber(p.cost_basis_eur),
  price: (p) => toNumber(p.price?.close),
  value: (p) => toNumber(p.market_value_eur),
  unrealized: (p) => toNumber(p.unrealized_pnl_eur),
  day: (p) => toNumber(p.day_change_eur),
  weight: (p) => toNumber(p.weight),
}

export function Holdings() {
  const { t } = useTranslation()
  const [tab, setTab] = useState<Tab>('positions')
  const [adding, setAdding] = useState(false)
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-semibold">{t('holdings.title')}</h1>
        <Button onClick={() => setAdding(true)}>{t('holdings.add')}</Button>
      </div>
      <div role="tablist" className="flex gap-1" aria-label={t('holdings.title')}>
        {(['positions', 'instruments'] as const).map((id) => (
          <button
            key={id}
            role="tab"
            aria-selected={tab === id}
            onClick={() => setTab(id)}
            className={cn(
              'rounded-md px-3 py-2 text-sm',
              tab === id ? 'bg-primary text-primary-foreground' : 'hover:bg-border/40',
            )}
          >
            {t(`holdings.tabs.${id}`)}
          </button>
        ))}
      </div>
      {tab === 'positions' ? (
        <PositionsTab onAdd={() => setAdding(true)} />
      ) : (
        <InstrumentsTab onAdd={() => setAdding(true)} />
      )}
      <AddInstrumentDialog open={adding} onClose={() => setAdding(false)} />
    </div>
  )
}

function PositionsTab({ onAdd }: { onAdd: () => void }) {
  const { t } = useTranslation()
  const { eur, qty, pct } = useFormat()
  const [account, setAccount] = useState<number | undefined>()
  const [includeClosed, setIncludeClosed] = useState(false)
  const [group, setGroup] = useState(false)
  const accounts = useAccounts()
  const instruments = useInstruments('all')
  const { data, isPending, isError, error } = usePositions({ account, includeClosed })
  const rows = useMemo(() => data?.positions ?? [], [data])
  const { sorted, sort, toggle } = useSort<Position, SortKey>(rows, ACCESSORS, {
    key: 'value',
    dir: 'desc',
  })

  const groups = useMemo(() => {
    if (!group) return [{ name: null as string | null, rows: sorted }]
    const byAccount = new Map<string, Position[]>()
    for (const p of sorted)
      byAccount.set(p.account_name, [...(byAccount.get(p.account_name) ?? []), p])
    return [...byAccount].map(([name, list]) => ({ name, rows: list }))
  }, [sorted, group])

  if (isPending) return <p role="status">{t('app.loading')}</p>
  if (isError) return <Alert>{errorMessage(error)}</Alert>

  const toolbar = (
    <div className="flex flex-wrap items-center gap-4">
      <label className="flex items-center gap-2 text-sm">
        {t('holdings.account')}
        <Select
          className="w-auto"
          value={account ?? ''}
          onChange={(e) => setAccount(e.target.value ? Number(e.target.value) : undefined)}
        >
          <option value="">{t('holdings.allAccounts')}</option>
          {accounts.data?.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </Select>
      </label>
      <Checkbox
        label={t('holdings.showClosed')}
        checked={includeClosed}
        onChange={(e) => setIncludeClosed(e.target.checked)}
      />
      <Checkbox
        label={t('holdings.groupByAccount')}
        checked={group}
        onChange={(e) => setGroup(e.target.checked)}
      />
    </div>
  )

  if (rows.length === 0) {
    const hasInstruments = (instruments.data?.length ?? 0) > 0
    return (
      <div className="space-y-4">
        {toolbar}
        {hasInstruments ? (
          <EmptyState
            title={t('holdings.noTransactions.title')}
            body={t('holdings.noTransactions.body')}
            action={
              <Link
                to="/transactions?add=buy"
                className="inline-flex min-h-10 items-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground"
              >
                {t('holdings.noTransactions.action')}
              </Link>
            }
          />
        ) : (
          <EmptyState
            title={t('holdings.empty.title')}
            body={t('holdings.empty.body')}
            action={<Button onClick={onAdd}>{t('holdings.add')}</Button>}
          />
        )}
      </div>
    )
  }

  const totals = data.totals
  const showAccount = group || (accounts.data?.length ?? 0) > 1
  return (
    <div className="space-y-3">
      {toolbar}
      {totals.unvalued_positions > 0 && (
        <Alert>{t('holdings.unvalued', { count: totals.unvalued_positions })}</Alert>
      )}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[60rem] border-collapse text-sm">
          <caption className="sr-only">{t('holdings.caption')}</caption>
          <thead>
            <tr className="border-b border-border">
              <SortHeader
                align="left"
                label={t('holdings.columns.name')}
                sortKey="name"
                sort={sort}
                onSort={toggle}
              />
              {showAccount && (
                <SortHeader
                  align="left"
                  label={t('holdings.columns.account')}
                  sortKey="account"
                  sort={sort}
                  onSort={toggle}
                />
              )}
              <SortHeader
                label={t('holdings.columns.quantity')}
                sortKey="quantity"
                sort={sort}
                onSort={toggle}
              />
              <SortHeader
                label={t('holdings.columns.avgCost')}
                sortKey="avgCost"
                sort={sort}
                onSort={toggle}
              />
              <SortHeader
                label={t('holdings.columns.cost')}
                sortKey="cost"
                sort={sort}
                onSort={toggle}
              />
              <SortHeader
                label={t('holdings.columns.price')}
                sortKey="price"
                sort={sort}
                onSort={toggle}
              />
              <SortHeader
                label={t('holdings.columns.value')}
                sortKey="value"
                sort={sort}
                onSort={toggle}
              />
              <SortHeader
                label={t('holdings.columns.unrealized')}
                sortKey="unrealized"
                sort={sort}
                onSort={toggle}
              />
              <SortHeader
                label={t('holdings.columns.day')}
                sortKey="day"
                sort={sort}
                onSort={toggle}
              />
              <SortHeader
                label={t('holdings.columns.weight')}
                sortKey="weight"
                sort={sort}
                onSort={toggle}
              />
            </tr>
          </thead>
          {groups.map((g) => (
            <tbody key={g.name ?? 'all'}>
              {g.name !== null && (
                <tr className="bg-border/30">
                  <th
                    scope="rowgroup"
                    colSpan={showAccount ? 10 : 9}
                    className="px-3 py-1 text-left font-medium"
                  >
                    {g.name}
                  </th>
                </tr>
              )}
              {g.rows.map((p) => (
                <tr
                  key={`${p.account_id}-${p.instrument_id}`}
                  className="border-b border-border align-top"
                >
                  <td className="px-3 py-2">
                    <Link
                      to={`/holdings/${p.instrument_id}`}
                      className="font-medium hover:underline"
                    >
                      {p.name}
                    </Link>
                    <div className="text-xs text-muted">
                      {[p.ticker, p.isin].filter(Boolean).join(' · ')}
                    </div>
                  </td>
                  {showAccount && <td className="px-3 py-2">{p.account_name}</td>}
                  <td className="px-3 py-2 text-right tabular-nums">{qty(p.quantity)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {p.avg_cost_eur ? eur(p.avg_cost_eur) : '–'}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{eur(p.cost_basis_eur)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {p.price ? (
                      <AsOf date={p.price.date} source={p.price.source}>
                        {eur(p.price.close)}
                        {p.currency && p.currency !== 'EUR' && (
                          <span className="ml-1 text-xs text-muted">{p.currency}</span>
                        )}
                        {p.price.stale && (
                          <div>
                            <Badge tone="warn" title={t('holdings.staleHint')}>
                              {t('holdings.stale')}
                            </Badge>
                          </div>
                        )}
                      </AsOf>
                    ) : (
                      <span className="text-muted" title={p.note ?? undefined}>
                        {t('holdings.noPrice')}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{eur(p.market_value_eur)}</td>
                  <td className="px-3 py-2 text-right">
                    <Gain eur={p.unrealized_pnl_eur} ratio={p.unrealized_ratio} />
                  </td>
                  <td className="px-3 py-2 text-right">
                    <Gain eur={p.day_change_eur} ratio={p.day_change_ratio} />
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {p.weight ? pct(p.weight, 1) : '–'}
                  </td>
                </tr>
              ))}
            </tbody>
          ))}
          <tfoot>
            <tr className="font-medium">
              <th scope="row" colSpan={showAccount ? 4 : 3} className="px-3 py-2 text-left">
                {t('holdings.totals')}
              </th>
              <td className="px-3 py-2 text-right tabular-nums">{eur(totals.cost_basis_eur)}</td>
              <td />
              <td className="px-3 py-2 text-right tabular-nums">{eur(totals.market_value_eur)}</td>
              <td className="px-3 py-2 text-right">
                <Gain eur={totals.unrealized_pnl_eur} ratio={totals.unrealized_ratio} />
              </td>
              <td className="px-3 py-2 text-right">
                <Gain eur={totals.day_change_eur} />
              </td>
              <td />
            </tr>
          </tfoot>
        </table>
      </div>
      <p className="text-sm text-muted">
        {t('holdings.realized')}: {eur(totals.realized_pnl_eur)} · {t('holdings.income')}:{' '}
        {eur(totals.income_eur)}
      </p>
    </div>
  )
}
