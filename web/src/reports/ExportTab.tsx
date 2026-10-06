import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAccounts } from '../api/queries'
import { Field, Select } from '../components/ui'

const LINK =
  'inline-flex min-h-10 items-center rounded-md border border-border px-4 text-sm font-medium hover:bg-border/40'

/** Download your data (FR-TX-13): every posted transaction in the layout the import wizard
 * recognises, and the open positions, as CSV or JSON. */
export function ExportTab() {
  const { t } = useTranslation()
  const accounts = useAccounts()
  const [account, setAccount] = useState('')
  const suffix = account ? `&account=${account}` : ''
  const url = (kind: 'transactions' | 'positions', format: 'csv' | 'json') =>
    `/api/v1/export/${kind}?format=${format}${suffix}`

  return (
    <div className="max-w-2xl space-y-6">
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
      <section aria-labelledby="exp-tx" className="space-y-2">
        <h2 id="exp-tx" className="text-lg font-medium">
          {t('exportData.transactions.title')}
        </h2>
        <p className="text-sm text-muted">{t('exportData.transactions.help')}</p>
        <div className="flex flex-wrap gap-2">
          <a href={url('transactions', 'csv')} download className={LINK}>
            {t('exportData.csv')}
          </a>
          <a href={url('transactions', 'json')} download className={LINK}>
            {t('exportData.json')}
          </a>
        </div>
      </section>
      <section aria-labelledby="exp-pos" className="space-y-2">
        <h2 id="exp-pos" className="text-lg font-medium">
          {t('exportData.positions.title')}
        </h2>
        <p className="text-sm text-muted">{t('exportData.positions.help')}</p>
        <div className="flex flex-wrap gap-2">
          <a href={url('positions', 'csv')} download className={LINK}>
            {t('exportData.csv')}
          </a>
          <a href={url('positions', 'json')} download className={LINK}>
            {t('exportData.json')}
          </a>
        </div>
      </section>
    </div>
  )
}
