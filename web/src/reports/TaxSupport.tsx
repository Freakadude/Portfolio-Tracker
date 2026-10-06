import { useQuery } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { api, errorMessage, unwrap } from '../api/client'
import { useAccounts } from '../api/queries'
import { Delta, EmptyState } from '../components/display'
import { Alert, Button, Field, Select } from '../components/ui'
import { useFormat } from '../lib/useFormat'

type Holding = {
  account: string
  instrument: string
  isin: string | null
  quantity: string
  value_eur: string | null
  cost_basis_eur: string
}

/** The annual tax-support report (FR-PF-11): what a tax return asks about one calendar year.
 * It prints cleanly, so "Print or save as PDF" in the browser makes the PDF. */
export function TaxSupport() {
  const { t } = useTranslation()
  const years = useQuery({
    queryKey: ['reports', 'tax-years'],
    queryFn: () => unwrap(api.GET('/api/v1/reports/tax-years')),
  })
  if (years.isPending) return <p role="status">{t('app.loading')}</p>
  if (years.isError) return <Alert>{errorMessage(years.error)}</Alert>
  if (years.data.length === 0)
    return <EmptyState title={t('tax.empty.title')} body={t('tax.empty.body')} />
  return <Report years={years.data} />
}

function Report({ years }: { years: number[] }) {
  const { t } = useTranslation()
  const { eur } = useFormat()
  const accounts = useAccounts()
  const [year, setYear] = useState(years[0])
  const [account, setAccount] = useState('')
  const accountId = account ? Number(account) : undefined
  const report = useQuery({
    queryKey: ['reports', 'tax-support', year, accountId],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/reports/tax-support', {
          params: { query: { year, account: accountId } },
        }),
      ),
  })
  const csv = `/api/v1/reports/tax-support?year=${year}&format=csv${accountId ? `&account=${accountId}` : ''}`
  const r = report.data

  const row = (label: string, value: ReactNode, hint?: string) => (
    <tr className="border-b border-border">
      <th scope="row" className="py-2 pr-3 text-left font-normal">
        {label}
        {hint && <div className="text-xs text-muted">{hint}</div>}
      </th>
      <td className="py-2 text-right tabular-nums">{value}</td>
    </tr>
  )

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end gap-4 print:hidden">
        <Field label={t('reports.year')}>
          {(p) => (
            <Select value={year} onChange={(e) => setYear(Number(e.target.value))} {...p}>
              {years.map((y) => (
                <option key={y} value={y}>
                  {y}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label={t('reports.account')}>
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
        <a
          href={csv}
          download
          className="inline-flex min-h-10 items-center rounded-md border border-border px-4 text-sm font-medium hover:bg-border/40"
        >
          {t('reports.download')}
        </a>
        <Button variant="secondary" onClick={() => window.print()}>
          {t('tax.print')}
        </Button>
      </div>
      {report.isError && <Alert>{errorMessage(report.error)}</Alert>}
      {r && (
        <article aria-label={t('tax.title', { year })} className="space-y-6">
          <header>
            <h2 className="text-xl font-semibold">{t('tax.title', { year })}</h2>
            <p className="text-sm text-muted">
              {r.start} – {r.end}
              {account && accounts.data
                ? `, ${accounts.data.find((a) => a.id === accountId)?.name ?? ''}`
                : ''}
            </p>
            {r.partial && <p className="text-sm text-muted">{t('tax.partial', { end: r.end })}</p>}
          </header>
          {(r.unvalued_start > 0 || r.unvalued_end > 0) && (
            <Alert>
              {t('tax.unvalued', { count: Math.max(r.unvalued_start, r.unvalued_end) })}
            </Alert>
          )}
          <table className="w-full max-w-2xl text-sm">
            <caption className="sr-only">{t('tax.caption', { year })}</caption>
            <tbody>
              {row(t('tax.valueOn', { date: r.start }), eur(r.value_start_eur))}
              {row(t('tax.valueOn', { date: r.end }), eur(r.value_end_eur))}
              {row(t('tax.moneyIn'), eur(r.money_in_eur), t('tax.flowHint'))}
              {row(t('tax.moneyOut'), eur(r.money_out_eur))}
              {row(t('tax.netContributions'), <Delta value={r.net_contributions_eur} />)}
              {row(t('tax.incomeGross'), eur(r.income_gross_eur))}
              {row(t('tax.withholding'), eur(r.withholding_eur))}
              {row(t('tax.incomeNet'), eur(r.income_net_eur))}
              {row(t('tax.tradeCosts'), eur(r.trade_costs_eur))}
              {row(t('tax.otherCosts'), eur(r.other_costs_eur))}
              {row(t('tax.proceeds'), eur(r.realized_proceeds_eur))}
              {row(t('tax.cost'), eur(r.realized_cost_eur))}
              {row(t('tax.realized'), <Delta value={r.realized_result_eur} />)}
              {row(t('tax.unrealizedOn', { date: r.start }), eur(r.unrealized_start_eur))}
              {row(t('tax.unrealizedOn', { date: r.end }), eur(r.unrealized_end_eur))}
              {row(t('tax.unrealizedChange'), <Delta value={r.unrealized_change_eur} />)}
            </tbody>
          </table>
          <Holdings title={t('tax.holdingsOn', { date: r.start })} rows={r.holdings_start} />
          <Holdings title={t('tax.holdingsOn', { date: r.end })} rows={r.holdings_end} />
          <p className="max-w-2xl text-sm text-muted">{r.note}</p>
        </article>
      )}
    </div>
  )
}

function Holdings({ title, rows }: { title: string; rows: Holding[] }) {
  const { t } = useTranslation()
  const { eur, qty } = useFormat()
  return (
    <section className="space-y-2" aria-label={title}>
      <h3 className="text-lg font-medium">{title}</h3>
      {rows.length === 0 ? (
        <p className="text-muted">{t('tax.noHoldings')}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <caption className="sr-only">{title}</caption>
            <thead>
              <tr className="border-b border-border text-left">
                <th scope="col" className="py-2 pr-3 font-medium">
                  {t('tax.columns.instrument')}
                </th>
                <th scope="col" className="py-2 pr-3 font-medium">
                  {t('tax.columns.account')}
                </th>
                <th scope="col" className="py-2 pr-3 text-right font-medium">
                  {t('tax.columns.units')}
                </th>
                <th scope="col" className="py-2 pr-3 text-right font-medium">
                  {t('tax.columns.value')}
                </th>
                <th scope="col" className="py-2 text-right font-medium">
                  {t('tax.columns.cost')}
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((h) => (
                <tr key={`${h.account}:${h.instrument}`} className="border-b border-border">
                  <td className="py-2 pr-3">
                    {h.instrument}
                    {h.isin && <div className="text-xs text-muted">{h.isin}</div>}
                  </td>
                  <td className="py-2 pr-3">{h.account}</td>
                  <td className="py-2 pr-3 text-right tabular-nums">{qty(h.quantity)}</td>
                  <td className="py-2 pr-3 text-right tabular-nums">
                    {h.value_eur === null ? '–' : eur(h.value_eur)}
                  </td>
                  <td className="py-2 text-right tabular-nums">{eur(h.cost_basis_eur)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
