import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'
import { errorMessage } from '../api/client'
import { useAccounts } from '../api/queries'
import { EmptyState } from '../components/display'
import { Alert, Button, Input, Select } from '../components/ui'
import { cn } from '../lib/cn'
import { useFormat } from '../lib/useFormat'
import { AddWidgetDialog } from './AddWidgetDialog'
import { ConfigPanel } from './ConfigPanel'
import { DashboardView, type Breakpoint } from './DashboardView'
import { ScopeFilter } from './ScopeFilter'
import {
  useDashboardActions,
  useDashboards,
  usePriceStatus,
  useTabDashboard,
  type Box,
  type Config,
  type Dashboard,
  type DashboardWidget,
  type Filters,
  type Layouts,
} from './api'

export const PERIODS = ['1D', '1W', '1M', '3M', 'YTD', '1Y', '3Y', '5Y', 'MAX'] as const

/** A dashboard on screen: its period and account filters, the grid, and edit mode (FR-DB-02,
 * FR-DB-03, FR-DB-05). Used for Home (the default dashboard) and for any dashboard by id. */
export function DashboardHost({ dashboard }: { dashboard: Dashboard }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const actions = useDashboardActions()
  const list = useDashboards()
  const [tab, setTab] = useTabDashboard()
  const isTab = tab === dashboard.id
  const accounts = useAccounts()
  const prices = usePriceStatus()
  const { when } = useFormat()
  const [editing, setEditing] = useState(false)
  const [adding, setAdding] = useState(false)
  const [configuring, setConfiguring] = useState<DashboardWidget | null>(null)
  const [breakpoint, setBreakpoint] = useState<Breakpoint>('lg')
  const saved = (dashboard.filters ?? {}) as Filters
  const [filters, setFilters] = useState<Filters>({
    period: saved.period ?? 'YTD',
    account: saved.account ?? null,
    start: saved.start ?? null,
    end: saved.end ?? null,
    types: saved.types ?? [],
    instruments: saved.instruments ?? [],
    hidden: saved.hidden ?? [],
  })

  // the filters belong to the dashboard: saved a moment after they stop changing
  const first = useRef(true)
  useEffect(() => {
    if (first.current) {
      first.current = false
      return
    }
    const id = setTimeout(() => actions.setFilters.mutate({ id: dashboard.id, filters }), 400)
    return () => clearTimeout(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters, dashboard.id])

  const error = actions.saveLayout.error ?? actions.addWidget.error ?? actions.removeWidget.error
  const boxOf = (w: DashboardWidget): Box | undefined =>
    ((dashboard.layouts as Layouts)[breakpoint] ?? []).find((b) => b.i === String(w.id))
  const hidden = filters.hidden ?? []
  const hide = (bar: 'timeframe' | 'scope') =>
    setFilters((f) => ({
      ...f,
      hidden: [...(f.hidden ?? []).filter((b) => b !== bar), bar],
      // a filter that is out of sight must not keep narrowing the widgets
      ...(bar === 'scope' ? { account: null, types: [], instruments: [] } : {}),
    }))
  const bringBack = (bar: 'timeframe' | 'scope') =>
    setFilters((f) => ({ ...f, hidden: (f.hidden ?? []).filter((b) => b !== bar) }))
  const clone = (w: DashboardWidget) => {
    const lg = (dashboard.layouts as Layouts).lg ?? []
    const own = lg.find((b) => b.i === String(w.id))
    const config = JSON.parse(JSON.stringify(w.config)) as Config
    if (typeof config.title === 'string' && config.title.trim()) {
      config.title = `${config.title.slice(0, 92)} (copy)`
    }
    actions.addWidget.mutate({
      id: dashboard.id,
      type: w.type,
      config,
      // the same size, under the lowest widget
      grid: own ? { ...own, y: lg.reduce((low, b) => Math.max(low, b.y + b.h), 0) } : undefined,
    })
  }
  const customReady = Boolean(filters.start && filters.end && filters.start <= filters.end)
  // an unfinished custom range keeps showing the year to date instead of failing every widget
  const effective = useMemo<Filters>(
    () => (filters.period === 'CUSTOM' && !customReady ? { ...filters, period: 'YTD' } : filters),
    [filters, customReady],
  )

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-semibold">{dashboard.name}</h1>
        <div className="flex flex-wrap items-center gap-2">
          {list.data && list.data.length > 1 && (
            <Select
              aria-label={t('dashboard.switch')}
              value={dashboard.id}
              onChange={(e) => navigate(`/dashboards/${e.target.value}`)}
              className="w-auto"
            >
              {list.data.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </Select>
          )}
          <Button
            variant="secondary"
            onClick={() => {
              void queryClient.invalidateQueries({ queryKey: ['widget-data'] })
              void queryClient.invalidateQueries({ queryKey: ['price-status'] })
            }}
          >
            {t('dashboard.refresh')}
          </Button>
          {editing && (
            <Button variant="secondary" onClick={() => setAdding(true)}>
              {t('dashboard.addWidget')}
            </Button>
          )}
          <Button
            variant={editing ? 'primary' : 'secondary'}
            onClick={() => setEditing((v) => !v)}
            aria-pressed={editing}
          >
            {t(editing ? 'dashboard.done' : 'dashboard.edit')}
          </Button>
          <Button
            variant={isTab ? 'primary' : 'secondary'}
            aria-pressed={isTab}
            title={t('dashboard.tabHint')}
            onClick={() => setTab(isTab ? null : dashboard.id)}
          >
            {t(isTab ? 'dashboard.tabIsThis' : 'dashboard.tabMakeThis')}
          </Button>
          <Link
            to="/dashboards/all"
            className="rounded-md border border-border px-3 py-2 text-sm hover:bg-border/40"
          >
            {t('dashboard.manage')}
          </Link>
        </div>
      </div>

      {prices.data && prices.data.holdings_total > 0 && (
        <p className="text-sm text-muted" data-testid="price-status">
          {prices.data.last_checked_at
            ? t('dashboard.pricesChecked', { when: when(prices.data.last_checked_at) })
            : t('dashboard.pricesNeverChecked')}
          {prices.data.newest_close && (
            <> {t('dashboard.pricesNewestClose', { date: prices.data.newest_close })}</>
          )}
          {prices.data.last_quote_at && (
            <> {t('dashboard.pricesQuote', { when: when(prices.data.last_quote_at) })}</>
          )}
          {prices.data.holdings_priced < prices.data.holdings_total && (
            <>
              {' '}
              {t('dashboard.pricesMissing', {
                count: prices.data.holdings_total - prices.data.holdings_priced,
              })}
            </>
          )}
        </p>
      )}

      <div
        className="flex flex-wrap items-end gap-4"
        role="group"
        aria-label={t('dashboard.filters')}
      >
        {!hidden.includes('timeframe') && (
          <>
            <div
              role="group"
              aria-label={t('overview.periods.label')}
              className="flex flex-wrap gap-1"
            >
              {PERIODS.map((p) => (
                <button
                  key={p}
                  type="button"
                  aria-pressed={filters.period === p}
                  onClick={() => setFilters((f) => ({ ...f, period: p }))}
                  className={cn(
                    'min-h-9 rounded-md px-3 text-sm',
                    filters.period === p
                      ? 'bg-primary text-primary-foreground'
                      : 'border border-border hover:bg-border/40',
                  )}
                >
                  {t(`overview.periods.${p}`)}
                </button>
              ))}
              <button
                type="button"
                aria-pressed={filters.period === 'CUSTOM'}
                onClick={() => setFilters((f) => ({ ...f, period: 'CUSTOM' }))}
                className={cn(
                  'min-h-9 rounded-md px-3 text-sm',
                  filters.period === 'CUSTOM'
                    ? 'bg-primary text-primary-foreground'
                    : 'border border-border hover:bg-border/40',
                )}
              >
                {t('overview.periods.CUSTOM')}
              </button>
            </div>
            {filters.period === 'CUSTOM' && (
              <div className="flex flex-wrap items-end gap-2">
                <label className="text-sm">
                  <span className="mb-1 block font-medium">{t('overview.from')}</span>
                  <Input
                    type="date"
                    value={filters.start ?? ''}
                    onChange={(e) => setFilters((f) => ({ ...f, start: e.target.value || null }))}
                  />
                </label>
                <label className="text-sm">
                  <span className="mb-1 block font-medium">{t('overview.to')}</span>
                  <Input
                    type="date"
                    value={filters.end ?? ''}
                    onChange={(e) => setFilters((f) => ({ ...f, end: e.target.value || null }))}
                  />
                </label>
                {!customReady && (
                  <p className="text-sm text-muted">{t('overview.customInvalid')}</p>
                )}
              </div>
            )}
            {editing && (
              <Button variant="ghost" className="min-h-9" onClick={() => hide('timeframe')}>
                {t('dashboard.removeFilter.timeframe')}
              </Button>
            )}
          </>
        )}
        {!hidden.includes('scope') && accounts.data && accounts.data.length > 1 && (
          <Select
            aria-label={t('overview.account')}
            value={filters.account ?? ''}
            onChange={(e) =>
              setFilters((f) => ({ ...f, account: e.target.value ? Number(e.target.value) : null }))
            }
            className="w-auto"
          >
            <option value="">{t('overview.allAccounts')}</option>
            {accounts.data.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </Select>
        )}
      </div>

      {!hidden.includes('scope') && (
        <ScopeFilter
          filters={filters}
          onChange={(patch) => setFilters((f) => ({ ...f, ...patch }))}
        />
      )}
      {editing && !hidden.includes('scope') && (
        <div>
          <Button variant="ghost" className="min-h-9" onClick={() => hide('scope')}>
            {t('dashboard.removeFilter.scope')}
          </Button>
        </div>
      )}
      {editing &&
        (['timeframe', 'scope'] as const)
          .filter((bar) => hidden.includes(bar))
          .map((bar) => (
            <div
              key={bar}
              className="flex flex-wrap items-center gap-3 rounded-md border border-dashed border-border px-3 py-2 text-sm text-muted"
            >
              <span>{t(`dashboard.removed.${bar}`)}</span>
              {bar === 'timeframe' && (
                <span>
                  {t('dashboard.removed.keeps', {
                    period: t(`overview.periods.${effective.period ?? 'YTD'}`),
                  })}
                </span>
              )}
              <Button variant="secondary" className="min-h-8" onClick={() => bringBack(bar)}>
                {t('dashboard.addBack')}
              </Button>
            </div>
          ))}

      {error !== undefined && error !== null && <Alert>{errorMessage(error)}</Alert>}
      {dashboard.widgets.length === 0 ? (
        <EmptyState
          title={t('dashboard.empty.title')}
          body={t('dashboard.empty.body')}
          action={
            <Button
              onClick={() => {
                setEditing(true)
                setAdding(true)
              }}
            >
              {t('dashboard.addWidget')}
            </Button>
          }
        />
      ) : (
        <DashboardView
          dashboard={dashboard}
          filters={effective}
          editing={editing}
          onBreakpoint={setBreakpoint}
          onLayoutChange={(layouts) => actions.saveLayout.mutate({ id: dashboard.id, layouts })}
          onConfigure={setConfiguring}
          onClone={clone}
          onRemove={(w) => {
            if (window.confirm(t('dashboard.removeConfirm')))
              actions.removeWidget.mutate({ id: dashboard.id, widgetId: w.id })
          }}
        />
      )}

      {adding && (
        <AddWidgetDialog
          onClose={() => setAdding(false)}
          onAdd={(type, config) =>
            actions.addWidget.mutate(
              { id: dashboard.id, type, config },
              { onSuccess: () => setAdding(false) },
            )
          }
        />
      )}
      {configuring && (
        <ConfigPanel
          key={configuring.id}
          widget={configuring}
          breakpoint={breakpoint}
          box={boxOf(configuring)}
          filters={effective}
          saving={actions.updateWidget.isPending || actions.saveLayout.isPending}
          error={actions.updateWidget.error}
          onClose={() => setConfiguring(null)}
          onSave={(config: Config, box: Box | undefined) => {
            const widget = configuring
            actions.updateWidget.mutate(
              { id: dashboard.id, widgetId: widget.id, config },
              {
                onSuccess: () => {
                  if (box) {
                    const layouts = dashboard.layouts as Layouts
                    actions.saveLayout.mutate({
                      id: dashboard.id,
                      layouts: {
                        ...layouts,
                        [breakpoint]: (layouts[breakpoint] ?? []).map((b) =>
                          b.i === String(widget.id) ? { ...b, ...box } : b,
                        ),
                      },
                    })
                  }
                  setConfiguring(null)
                },
              },
            )
          }}
        />
      )}
    </div>
  )
}
