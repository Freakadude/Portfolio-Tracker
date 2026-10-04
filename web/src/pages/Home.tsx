import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { errorMessage } from '../api/client'
import { useAccounts, usePortfolioSummary } from '../api/queries'
import { AsOf, EmptyState, Gain } from '../components/display'
import { Alert, Field, Input, Select } from '../components/ui'
import { cn } from '../lib/cn'
import { useFormat } from '../lib/useFormat'

const PERIODS = ['1D', '1W', '1M', '3M', 'YTD', '1Y', '3Y', '5Y', 'MAX', 'CUSTOM'] as const
type Period = (typeof PERIODS)[number]

const linkButton =
  'inline-flex min-h-10 items-center rounded-md border border-border px-4 text-sm font-medium hover:bg-border/40'

export function Home() {
  const { t } = useTranslation()
  const { eur } = useFormat()
  const accounts = useAccounts()
  const [period, setPeriod] = useState<Period>('YTD')
  const [account, setAccount] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')

  const customReady = period !== 'CUSTOM' || (Boolean(from) && Boolean(to) && from <= to)
  const summary = usePortfolioSummary({
    period,
    account: account ? Number(account) : undefined,
    from: period === 'CUSTOM' ? from : undefined,
    to: period === 'CUSTOM' ? to : undefined,
  })
  const empty = accounts.isSuccess && accounts.data.every((a) => a.transaction_count === 0)

  if (empty) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-semibold">{t('overview.title')}</h1>
        <EmptyState
          title={t('empty.home.title')}
          body={t('empty.home.body')}
          action={
            <div className="flex flex-wrap gap-2">
              <Link to="/holdings" className={linkButton}>
                {t('overview.addInstrument')}
              </Link>
              <Link to="/transactions/import" className={linkButton}>
                {t('overview.importCsv')}
              </Link>
            </div>
          }
        />
      </div>
    )
  }

  const data = customReady ? summary.data : undefined
  const periodData = data?.period
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">{t('overview.title')}</h1>

      <div className="flex flex-wrap items-end gap-4">
        <div role="group" aria-label={t('overview.periods.label')} className="flex flex-wrap gap-1">
          {PERIODS.map((p) => (
            <button
              key={p}
              type="button"
              aria-pressed={period === p}
              onClick={() => setPeriod(p)}
              className={cn(
                'min-h-10 rounded-md px-3 text-sm',
                period === p
                  ? 'bg-primary text-primary-foreground'
                  : 'border border-border hover:bg-border/40',
              )}
            >
              {t(`overview.periods.${p}`)}
            </button>
          ))}
        </div>
        {accounts.data && accounts.data.length > 1 && (
          <Field label={t('overview.account')}>
            {(p) => (
              <Select value={account} onChange={(e) => setAccount(e.target.value)} {...p}>
                <option value="">{t('overview.allAccounts')}</option>
                {accounts.data?.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        )}
        {period === 'CUSTOM' && (
          <>
            <Field label={t('overview.from')}>
              {(p) => (
                <Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} {...p} />
              )}
            </Field>
            <Field label={t('overview.to')}>
              {(p) => (
                <Input type="date" value={to} onChange={(e) => setTo(e.target.value)} {...p} />
              )}
            </Field>
          </>
        )}
      </div>

      {!customReady && <p className="text-muted">{t('overview.customInvalid')}</p>}
      {summary.isError && customReady && <Alert>{errorMessage(summary.error)}</Alert>}
      {data && data.unvalued_positions > 0 && (
        <Alert>{t('overview.unvalued', { count: data.unvalued_positions })}</Alert>
      )}

      {data && periodData && (
        <>
          <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <Card label={t('overview.value')}>
              <AsOf date={data.price_date} source="">
                <span className="text-2xl font-semibold tabular-nums">{eur(data.value_eur)}</span>
              </AsOf>
            </Card>
            <Card label={t('overview.contributions')}>
              <span className="text-xl tabular-nums">{eur(data.net_contributions_eur)}</span>
            </Card>
            <Card label={t('overview.totalPnl')}>
              <Gain eur={data.total_pnl_eur} ratio={data.total_pnl_ratio} />
            </Card>
            <Card label={t('overview.dayChange')}>
              <Gain eur={data.day_change.pnl_eur} ratio={data.day_change.pnl_ratio} />
            </Card>
            <Card
              label={t('overview.periodPnl')}
              hint={t('overview.range', { start: periodData.start, end: periodData.end })}
            >
              <Gain eur={periodData.pnl_eur} ratio={periodData.pnl_ratio} />
            </Card>
            <Card label={t('overview.income')}>
              <span className="text-xl tabular-nums">{eur(periodData.income_eur)}</span>
            </Card>
            <Card label={t('overview.costs')}>
              <span className="text-xl tabular-nums">{eur(periodData.costs_eur)}</span>
            </Card>
          </dl>
          <p className="text-sm text-muted">
            {data.price_date
              ? t('overview.pricesAsOf', { date: data.price_date })
              : t('overview.noPrices')}
          </p>
        </>
      )}
    </div>
  )
}

function Card({
  label,
  hint,
  children,
}: {
  label: string
  hint?: string
  children: React.ReactNode
}) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <dt className="text-sm text-muted">{label}</dt>
      <dd className="mt-1">{children}</dd>
      {hint && <dd className="mt-1 text-xs text-muted">{hint}</dd>}
    </div>
  )
}
