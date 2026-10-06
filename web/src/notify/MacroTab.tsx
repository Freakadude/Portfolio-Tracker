import { useMutation } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api, errorMessage, unwrap } from '../api/client'
import { SectionForm } from '../components/SectionForm'
import { Alert, Button, Help } from '../components/ui'
import { useMacroSeries } from './api'

/** Settings, Macro: the indicator series fetched every morning, what is stored, and a way to
 * fetch now (FR-MD-08). FRED series need the free key under Providers. */
export function MacroTab() {
  const { t } = useTranslation()
  const series = useMacroSeries()
  const fetchNow = useMutation({ mutationFn: () => unwrap(api.POST('/api/v1/macro/refresh')) })
  return (
    <div className="space-y-6">
      <Help title={t('macroSettings.helpTitle')}>
        <p>{t('macroSettings.help1')}</p>
        <p>{t('macroSettings.help2')}</p>
        <p>{t('macroSettings.help3')}</p>
      </Help>
      <p className="text-sm text-muted">{t('macroSettings.intro')}</p>
      {series.isError && <Alert>{errorMessage(series.error)}</Alert>}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <caption className="mb-1 text-left font-medium">{t('macroSettings.stored')}</caption>
          <thead>
            <tr className="border-b border-border text-left">
              {(['name', 'code', 'source', 'last', 'points'] as const).map((c) => (
                <th key={c} scope="col" className="py-1 pr-3 font-medium">
                  {t(`macroSettings.columns.${c}`)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {series.data?.map((s) => (
              <tr key={s.code} className="border-b border-border">
                <td className="py-1 pr-3">
                  {s.name}
                  {!s.configured && (
                    <span className="ml-1 text-xs text-muted">
                      ({t('macroSettings.notListed')})
                    </span>
                  )}
                </td>
                <td className="py-1 pr-3 font-mono text-xs">{s.code}</td>
                <td className="py-1 pr-3">{s.source.toUpperCase()}</td>
                <td className="py-1 pr-3 tabular-nums">
                  {s.last_value === null
                    ? t('macroSettings.none')
                    : `${s.last_value} (${s.last_date})`}
                </td>
                <td className="py-1 pr-3 tabular-nums">{s.points}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex items-center gap-2">
        <Button variant="secondary" onClick={() => fetchNow.mutate()} disabled={fetchNow.isPending}>
          {t('macroSettings.fetchNow')}
        </Button>
        {fetchNow.isSuccess && (
          <span role="status" className="text-sm">
            {t('macroSettings.queued')}
          </span>
        )}
      </div>
      {fetchNow.isError && <Alert>{errorMessage(fetchNow.error)}</Alert>}
      <SectionForm section="macro" />
    </div>
  )
}
