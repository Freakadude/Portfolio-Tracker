import { Route, Routes } from 'react-router-dom'
import { Gate } from './components/Gate'
import { Layout } from './components/Layout'
import { Login } from './pages/Login'
import { Placeholder } from './pages/Placeholder'
import { Settings } from './pages/Settings'
import { Setup } from './pages/Setup'

const PAGES = [
  'holdings',
  'transactions',
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
          <Route path="settings" element={<Settings />} />
          <Route path="*" element={<Placeholder page="home" />} />
        </Route>
      </Route>
    </Routes>
  )
}
