import { Suspense, lazy } from 'react'
import { Route, Routes } from 'react-router-dom'
import { Gate, Loading } from './components/Gate'
import { Layout } from './components/Layout'
import { Holdings } from './pages/Holdings'
import { DashboardPage, Dashboards } from './pages/Dashboards'
import { Home } from './pages/Home'
import { Insights } from './pages/Insights'
import { ImportWizard } from './pages/ImportWizard'
import { Transactions } from './pages/Transactions'
import { Login } from './pages/Login'
import { Placeholder } from './pages/Placeholder'
import { Reports } from './pages/Reports'
import { Settings } from './pages/Settings'
import { Setup } from './pages/Setup'
import { Strategies } from './pages/Strategies'
import { System } from './pages/System'
import { Watchlist } from './pages/Watchlist'
import { WhatIf } from './pages/WhatIf'

// The chart library is large, so the position page is only loaded when it is opened.
const PositionDetail = lazy(() =>
  import('./pages/PositionDetail').then((m) => ({ default: m.PositionDetail })),
)

const PAGES = ['news'] as const

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/setup" element={<Setup />} />
      <Route element={<Gate />}>
        <Route element={<Layout />}>
          <Route index element={<Home />} />
          {PAGES.map((page) => (
            <Route key={page} path={page} element={<Placeholder page={page} />} />
          ))}
          <Route path="watchlist" element={<Watchlist />} />
          <Route path="strategies" element={<Strategies />} />
          <Route path="reports" element={<Reports />} />
          <Route path="what-if" element={<WhatIf />} />
          <Route path="holdings" element={<Holdings />} />
          <Route path="transactions" element={<Transactions />} />
          <Route path="transactions/import" element={<ImportWizard />} />
          <Route
            path="holdings/:instrumentId"
            element={
              <Suspense fallback={<Loading />}>
                <PositionDetail />
              </Suspense>
            }
          />
          <Route path="dashboards" element={<Dashboards />} />
          <Route path="dashboards/:dashboardId" element={<DashboardPage />} />
          <Route path="insights" element={<Insights />} />
          <Route path="system" element={<System />} />
          <Route path="settings" element={<Settings />} />
          <Route path="*" element={<Home />} />
        </Route>
      </Route>
    </Routes>
  )
}
