import { useTranslation } from 'react-i18next'
import { Navigate, Outlet } from 'react-router-dom'
import { useSetupStatus } from '../api/hooks'
import { Button } from './ui'

export function Loading() {
  const { t } = useTranslation()
  return (
    <p role="status" className="p-8 text-muted">
      {t('app.loading')}
    </p>
  )
}

/** Sends visitors to setup or login until they are signed in and setup is complete. */
export function Gate() {
  const { t } = useTranslation()
  const { data, isPending, isError, refetch } = useSetupStatus()
  if (isPending) return <Loading />
  if (isError)
    return (
      <div className="p-8">
        <Button onClick={() => refetch()}>{t('app.retry')}</Button>
      </div>
    )
  if (data.needs_owner || (data.authenticated && !data.setup_complete))
    return <Navigate to="/setup" replace />
  if (!data.authenticated) return <Navigate to="/login" replace />
  return <Outlet />
}
