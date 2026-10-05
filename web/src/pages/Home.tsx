import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { errorMessage } from '../api/client'
import { useAccounts } from '../api/queries'
import { Loading } from '../components/Gate'
import { EmptyState } from '../components/display'
import { Alert } from '../components/ui'
import { useDefaultDashboard } from '../dashboards/api'
import { LazyDashboardHost as DashboardHost } from '../dashboards/LazyHost'

const linkButton =
  'inline-flex min-h-10 items-center rounded-md border border-border px-4 text-sm font-medium hover:bg-border/40'

/** Home is the default dashboard (FR-DB-01). Until the first transaction there is nothing to
 * show, so a new owner is told what to do first instead of seeing empty widgets. */
export function Home() {
  const { t } = useTranslation()
  const accounts = useAccounts()
  const dashboard = useDefaultDashboard()
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
              <Link to="/dashboards" className={linkButton}>
                {t('dashboard.manage')}
              </Link>
            </div>
          }
        />
      </div>
    )
  }
  if (dashboard.isError) return <Alert>{errorMessage(dashboard.error)}</Alert>
  if (!dashboard.data || accounts.isPending) return <Loading />
  return <DashboardHost dashboard={dashboard.data} />
}
