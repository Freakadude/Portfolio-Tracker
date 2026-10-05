import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, errorMessage, unwrap } from '../api/client'
import { useAccounts } from '../api/queries'
import { Delta, EmptyState } from '../components/display'
import { Alert, Field, Select } from '../components/ui'
import { useFormat } from '../lib/useFormat'

/** Realized result and income per calendar year, account and instrument, as the lots matched
 * them (FR-TX-12). Support for a tax return, not tax advice. */
export function Reports() {
  const { t } = useTranslation()
  const years = useQuery({
    queryKey: ['reports', 'years'],
    queryFn: () => unwrap(api.GET('/api/v1/reports/years')),
  })
  if (years.isPending) return <p role="status">{t('app.loading')}</p>
  if (years.isError) return <Alert>{errorMessage(years.error)}</Alert>
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">{t('nav.reports')}</h1>
      {years.data.length === 0 ? (
        <EmptyState title={t('reports.empty.title')} body={t('reports.empty.body')} />
      ) : (
        <YearReport years={years.data} />
      )}
    </div>
  )
}

function YearReport({ years }: { years: number[] }) {
  const { t } = useTranslation()
  const { eur, qty } = useFormat()
  const accounts = useAccounts()
  const [year, setYear] = useState(years[0])
  const [account, setAccount] = useState('')
  const accountId = account ? Number(account) : undefined
  const report = useQuery({
    queryKey: ['reports', 'realized', year, accountId],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/reports/realized', { params: { query: { year, account: accountId } } }),
      ),
  })
  const csv = `/api/v1/reports/realized?year=${year}&format=csv${accountId ? `&account=${accountId}` : ''}`
  const data = report.data

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end gap-4">
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
      </div>
      <p className="max-w-2xl text-sm text-muted">{t('reports.disclaimer')}</p>
      {report.isError && <Alert>{errorMessage(report.error)}</Alert>}
      {data && (
        <>
          <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Total label={t('reports.totals.realized')}>
              <Delta value={data.realized_total_eur} />
            </Total>
            <Total label={t('reports.totals.income')}>{eur(data.income_gross_eur)}</Total>
            <Total label={t('reports.totals.withholding')}>{eur(data.withholding_eur)}</Total>
            <Total label={t('reports.totals.costs')}>{eur(data.costs_eur)}</Total>
          </dl>

          <section className="space-y-2">
            <h2 className="text-lg font-medium">{t('reports.realized.title')}</h2>
            {data.realized.length === 0 ? (
              <p className="text-muted">{t('reports.realized.none', { year })}</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <caption className="sr-only">{t('reports.realized.title')}</caption>
                  <thead>
                    <tr className="border-b border-border text-left">
                      {(
                        ['instrument', 'account', 'units', 'proceeds', 'cost', 'result'] as const
                      ).map((c) => (
                        <th
                          key={c}
                          scope="col"
                          className={`py-2 pr-3 font-medium ${
                            c === 'instrument' || c === 'account' ? '' : 'text-right'
                          }`}
                        >
                          {t(`reports.realized.columns.${c}`)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {data.realized.map((r) => (
                      <tr key={`${r.account}:${r.instrument}`} className="border-b border-border">
                        <td className="py-2 pr-3">
                          {r.instrument}
                          {r.isin && <div className="text-xs text-muted">{r.isin}</div>}
                        </td>
                        <td className="py-2 pr-3">{r.account}</td>
                        <td className="py-2 pr-3 text-right tabular-nums">{qty(r.quantity)}</td>
                        <td className="py-2 pr-3 text-right tabular-nums">{eur(r.proceeds_eur)}</td>
                        <td className="py-2 pr-3 text-right tabular-nums">{eur(r.cost_eur)}</td>
                        <td className="py-2 text-right">
                          <Delta value={r.result_eur} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="space-y-2">
            <h2 className="text-lg font-medium">{t('reports.income.title')}</h2>
            {data.income.length === 0 ? (
              <p className="text-muted">{t('reports.income.none', { year })}</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <caption className="sr-only">{t('reports.income.title')}</caption>
                  <thead>
                    <tr className="border-b border-border text-left">
                      {(['instrument', 'account', 'gross', 'withholding', 'net'] as const).map(
                        (c) => (
                          <th
                            key={c}
                            scope="col"
                            className={`py-2 pr-3 font-medium ${
                              c === 'instrument' || c === 'account' ? '' : 'text-right'
                            }`}
                          >
                            {t(`reports.income.columns.${c}`)}
                          </th>
                        ),
                      )}
                    </tr>
                  </thead>
                  <tbody>
                    {data.income.map((r) => (
                      <tr key={`${r.account}:${r.instrument}`} className="border-b border-border">
                        <td className="py-2 pr-3">
                          {r.instrument}
                          {r.isin && <div className="text-xs text-muted">{r.isin}</div>}
                        </td>
                        <td className="py-2 pr-3">{r.account}</td>
                        <td className="py-2 pr-3 text-right tabular-nums">{eur(r.gross_eur)}</td>
                        <td className="py-2 pr-3 text-right tabular-nums">
                          {eur(r.withholding_eur)}
                        </td>
                        <td className="py-2 text-right tabular-nums">{eur(r.net_eur)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  )
}

function Total({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-border p-3">
      <dt className="text-sm text-muted">{label}</dt>
      <dd className="mt-1 text-lg font-medium tabular-nums">{children}</dd>
    </div>
  )
}
