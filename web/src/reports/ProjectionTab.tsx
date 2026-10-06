import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, errorMessage, unwrap } from '../api/client'
import { useAccounts } from '../api/queries'
import { Alert, Field, Input, Select } from '../components/ui'
import { useFormat } from '../lib/useFormat'
import { ProjectionChart } from './ProjectionChart'

/** Monte Carlo projection of the portfolio (FR-PF-12) with assumptions you set. */
export function ProjectionTab() {
  const { t } = useTranslation()
  const { eur, num } = useFormat()
  const accounts = useAccounts()
  const [account, setAccount] = useState('')
  const [years, setYears] = useState('20')
  const [contribution, setContribution] = useState('0')
  const [ret, setRet] = useState('5')
  const [vol, setVol] = useState('15')
  const valid =
    Number.isInteger(Number(years)) &&
    Number(years) >= 1 &&
    Number(years) <= 40 &&
    [contribution, ret, vol].every((v) => v.trim() !== '' && Number.isFinite(Number(v)))
  const projection = useQuery({
    queryKey: ['projection', account, years, contribution, ret, vol],
    enabled: valid,
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/portfolio/projection', {
          params: {
            query: {
              years: Number(years),
              monthly_contribution: contribution,
              return_pct: ret,
              volatility_pct: vol,
              account: account ? Number(account) : undefined,
            },
          },
        }),
      ),
    retry: false,
  })
  const data = projection.data
  const last = data?.points[data.points.length - 1]
  const measured = data?.measured

  return (
    <div className="space-y-4">
      <p className="max-w-2xl text-sm text-muted">{t('projection.intro')}</p>
      <form
        className="grid max-w-3xl gap-4 sm:grid-cols-2 lg:grid-cols-5"
        aria-label={t('projection.form')}
        onSubmit={(e) => e.preventDefault()}
      >
        <Field label={t('projection.years')}>
          {(p) => (
            <Input
              inputMode="numeric"
              value={years}
              onChange={(e) => setYears(e.target.value)}
              {...p}
            />
          )}
        </Field>
        <Field label={t('projection.contribution')}>
          {(p) => (
            <Input
              inputMode="decimal"
              value={contribution}
              onChange={(e) => setContribution(e.target.value)}
              {...p}
            />
          )}
        </Field>
        <Field label={t('projection.return')}>
          {(p) => (
            <Input
              inputMode="decimal"
              value={ret}
              onChange={(e) => setRet(e.target.value)}
              {...p}
            />
          )}
        </Field>
        <Field label={t('projection.volatility')}>
          {(p) => (
            <Input
              inputMode="decimal"
              value={vol}
              onChange={(e) => setVol(e.target.value)}
              {...p}
            />
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
      </form>
      {!valid && <Alert>{t('projection.invalid')}</Alert>}
      {projection.isError && <Alert>{errorMessage(projection.error)}</Alert>}
      {measured && (
        <p className="text-sm text-muted">
          {t('projection.measured', {
            start: measured.start,
            end: measured.end,
            ret:
              measured.annual_return_pct === null ? '–' : `${num(measured.annual_return_pct, 1)} %`,
            vol:
              measured.annual_volatility_pct === null
                ? '–'
                : `${num(measured.annual_volatility_pct, 1)} %`,
          })}
        </p>
      )}
      {data && (
        <section aria-label={t('projection.chart')} className="flex h-[26rem] flex-col">
          <ProjectionChart
            assumptions={data.assumptions}
            rows={data.points
              .filter((p) => p.month % (data.assumptions.years <= 10 ? 1 : 3) === 0)
              .map((p) => ({
                date: p.date,
                invested: p.invested_eur,
                p10: p.p10_eur,
                median: p.median_eur,
                p90: p.p90_eur,
              }))}
          />
        </section>
      )}
      {data && last && (
        <p role="status" className="text-sm">
          {t('projection.summary', {
            date: last.date,
            median: eur(last.median_eur, 0),
            low: eur(last.p10_eur, 0),
            high: eur(last.p90_eur, 0),
          })}
        </p>
      )}
      {data && <p className="max-w-2xl text-sm text-muted">{data.note}</p>}
    </div>
  )
}
