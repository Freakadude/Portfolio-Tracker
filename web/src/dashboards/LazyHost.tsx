import { Suspense, lazy } from 'react'
import { Loading } from '../components/Gate'
import type { Dashboard } from './api'

// The charts are large, so the dashboard code is only fetched when a dashboard is opened.
const Host = lazy(() => import('./DashboardHost').then((m) => ({ default: m.DashboardHost })))

export function LazyDashboardHost({ dashboard }: { dashboard: Dashboard }) {
  return (
    <Suspense fallback={<Loading />}>
      <Host dashboard={dashboard} />
    </Suspense>
  )
}
