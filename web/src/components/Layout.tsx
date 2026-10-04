import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { api, unwrap } from '../api/client'
import { STATUS_KEY } from '../api/hooks'
import { Button } from './ui'
import { cn } from '../lib/cn'

export const NAV = [
  { to: '/', key: 'home', end: true },
  { to: '/holdings', key: 'holdings' },
  { to: '/transactions', key: 'transactions' },
  { to: '/dashboards', key: 'dashboards' },
  { to: '/insights', key: 'insights' },
  { to: '/news', key: 'news' },
  { to: '/strategies', key: 'strategies' },
  { to: '/watchlist', key: 'watchlist' },
  { to: '/reports', key: 'reports' },
  { to: '/settings', key: 'settings' },
  { to: '/system', key: 'system' },
] as const

/** Applies the saved theme (system, light or dark) to the document. */
function useTheme() {
  const { data } = useQuery({
    queryKey: ['settings', 'appearance'],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/settings/{section}', { params: { path: { section: 'appearance' } } }),
      ),
  })
  const theme = (data as { theme?: string } | undefined)?.theme
  useEffect(() => {
    const root = document.documentElement
    if (theme === 'light' || theme === 'dark') root.dataset.theme = theme
    else delete root.dataset.theme
  }, [theme])
}

export function Layout() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  useTheme()

  const signOut = useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/auth/logout')),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: STATUS_KEY })
      queryClient.removeQueries({ queryKey: ['settings'] })
      navigate('/login')
    },
  })

  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      <aside className="border-b border-border bg-card md:w-56 md:border-b-0 md:border-r">
        <div className="flex items-center justify-between px-4 py-3 md:block">
          <span className="text-lg font-semibold">{t('app.name')}</span>
        </div>
        <nav
          aria-label={t('nav.main')}
          className="flex gap-1 overflow-x-auto px-2 pb-2 md:flex-col md:pb-0"
        >
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={'end' in item ? item.end : false}
              className={({ isActive }) =>
                cn(
                  'whitespace-nowrap rounded-md px-3 py-2 text-sm',
                  isActive ? 'bg-primary text-primary-foreground' : 'hover:bg-border/40',
                )
              }
            >
              {t(`nav.${item.key}`)}
            </NavLink>
          ))}
        </nav>
        <div className="hidden px-2 py-4 md:block">
          <Button variant="ghost" className="w-full justify-start" onClick={() => signOut.mutate()}>
            {t('nav.signOut')}
          </Button>
        </div>
      </aside>
      <main className="min-w-0 flex-1 p-4 md:p-8">
        <Outlet />
        <div className="mt-8 md:hidden">
          <Button variant="secondary" onClick={() => signOut.mutate()}>
            {t('nav.signOut')}
          </Button>
        </div>
      </main>
    </div>
  )
}
