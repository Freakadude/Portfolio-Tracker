import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Dialog } from '../../components/display'
import { Button } from '../../components/ui'
import { useFormat } from '../../lib/useFormat'
import type { KpiData } from '../types'

/** The steps behind a return figure, drawn from the same series the figure was computed from, so
 * it can be followed by hand or in a spreadsheet. */
export function ReturnBreakdown({ data, onClose }: { data: KpiData; onClose: () => void }) {
  const { t } = useTranslation()
  const { eur, pct } = useFormat()
  const [copied, setCopied] = useState(false)
  const breakdown = data.breakdown
  if (!breakdown) return null

  const copy = (text: string) => {
    void navigator.clipboard
      ?.writeText(text)
      .then(() => setCopied(true))
      .catch(() => setCopied(false))
  }

  return (
    <Dialog open onClose={onClose} title={t(`breakdown.${breakdown.kind}.title`)} wide>
      <div className="space-y-4">
        {data.start && data.end && (
          <p className="text-sm text-muted">
            {t('breakdown.period', { start: data.start, end: data.end })}
          </p>
        )}
        <p className="max-w-3xl text-sm">{t(`breakdown.${breakdown.kind}.what`)}</p>

        {breakdown.kind === 'twr' ? (
          <>
            <p className="max-w-3xl text-sm">{t('breakdown.twr.steps')}</p>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <caption className="sr-only">{t('breakdown.twr.caption')}</caption>
                <thead>
                  <tr className="border-b border-border text-left">
                    <th scope="col" className="py-2 pr-3 font-medium">
                      {t('breakdown.columns.from')}
                    </th>
                    <th scope="col" className="py-2 pr-3 font-medium">
                      {t('breakdown.columns.to')}
                    </th>
                    <th scope="col" className="py-2 pr-3 text-right font-medium">
                      {t('breakdown.columns.moved')}
                    </th>
                    <th scope="col" className="py-2 pr-3 text-right font-medium">
                      {t('breakdown.columns.startCapital')}
                    </th>
                    <th scope="col" className="py-2 pr-3 text-right font-medium">
                      {t('breakdown.columns.endValue')}
                    </th>
                    <th scope="col" className="py-2 pr-3 text-right font-medium">
                      {t('breakdown.columns.income')}
                    </th>
                    <th scope="col" className="py-2 text-right font-medium">
                      {t('breakdown.columns.growth')}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {breakdown.segments.map((g) => (
                    <tr key={g.start} className="border-b border-border">
                      <td className="py-2 pr-3 whitespace-nowrap">{g.start}</td>
                      <td className="py-2 pr-3 whitespace-nowrap">{g.end}</td>
                      <td className="py-2 pr-3 text-right tabular-nums">{eur(g.flow)}</td>
                      <td className="py-2 pr-3 text-right tabular-nums">{eur(g.start_capital)}</td>
                      <td className="py-2 pr-3 text-right tabular-nums">{eur(g.end_value)}</td>
                      <td className="py-2 pr-3 text-right tabular-nums">{eur(g.income)}</td>
                      <td className="py-2 text-right tabular-nums">
                        {pct(String(Number(g.ratio) - 1))}
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr>
                    <th scope="row" colSpan={6} className="py-2 pr-3 text-left font-medium">
                      {t('breakdown.twr.together')}
                    </th>
                    <td className="py-2 text-right font-semibold tabular-nums">
                      {data.value === null ? '' : pct(data.value)}
                    </td>
                  </tr>
                </tfoot>
              </table>
            </div>
            <p className="max-w-3xl text-sm text-muted">{t('breakdown.twr.note')}</p>
          </>
        ) : (
          <>
            <p className="max-w-3xl text-sm">{t('breakdown.xirr.steps')}</p>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <caption className="sr-only">{t('breakdown.xirr.caption')}</caption>
                <thead>
                  <tr className="border-b border-border text-left">
                    <th scope="col" className="py-2 pr-3 font-medium">
                      {t('breakdown.columns.date')}
                    </th>
                    <th scope="col" className="py-2 pr-3 font-medium">
                      {t('breakdown.columns.what')}
                    </th>
                    <th scope="col" className="py-2 text-right font-medium">
                      {t('breakdown.columns.amount')}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {breakdown.flows.map((f, i) => (
                    <tr key={`${f.date}-${f.kind}-${i}`} className="border-b border-border">
                      <td className="py-2 pr-3 whitespace-nowrap">{f.date}</td>
                      <td className="py-2 pr-3">{t(`breakdown.kinds.${f.kind}`)}</td>
                      <td className="py-2 text-right tabular-nums">{eur(f.amount)}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr>
                    <th scope="row" colSpan={2} className="py-2 pr-3 text-left font-medium">
                      {t('breakdown.xirr.result')}
                    </th>
                    <td className="py-2 text-right font-semibold tabular-nums">
                      {data.value === null ? '' : pct(data.value)}
                    </td>
                  </tr>
                </tfoot>
              </table>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <Button
                variant="secondary"
                onClick={() =>
                  copy(
                    ['date\tamount', ...breakdown.flows.map((f) => `${f.date}\t${f.amount}`)].join(
                      '\n',
                    ),
                  )
                }
              >
                {t('breakdown.xirr.copy')}
              </Button>
              {copied && (
                <span role="status" className="text-sm text-muted">
                  {t('breakdown.xirr.copied')}
                </span>
              )}
            </div>
            <p className="max-w-3xl text-sm text-muted">{t('breakdown.xirr.note')}</p>
          </>
        )}
      </div>
    </Dialog>
  )
}
