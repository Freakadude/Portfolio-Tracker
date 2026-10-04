import { Suspense, lazy } from 'react'
import { Route, Routes } from 'react-router-dom'
import { Gate, Loading } from './components/Gate'
import { Layout } from './components/Layout'
import { Holdings } from './pages/Holdings'
import { ImportWizard } from './pages/ImportWizard'
import { Transactions } from './pages/Transactions'
import { Login } from './pages/Login'
import { Placeholder } from './pages/Placeholder'
import { Settings } from './pages/Settings'
import { Setup } from './pages/Setup'

// The chart library is large, so the position page is only loaded when it is opened.
const PositionDetail = lazy(() =>
  import('./pages/PositionDetail').then((m) => ({ default: m.PositionDetail })),
)

const PAGES = [
  'dashboards',
  'insights',
  'news',
  'strategies',
  'watchlist',
  'reports',
  'system',
] as const

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/setup" element={<Setup />} />
      <Route element={<Gate />}>
        <Route element={<Layout />}>
          <Route index element={<Placeholder page="home" />} />
          {PAGES.map((page) => (
            <Route key={page} path={page} element={<Placeholder page={page} />} />
          ))}
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
          <Route path="settings" element={<Settings />} />
          <Route path="*" element={<Placeholder page="home" />} />
        </Route>
      </Route>
    </Routes>
  )
}
