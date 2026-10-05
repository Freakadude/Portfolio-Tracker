import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'
import { errorMessage } from '../api/client'
import { useAccounts } from '../api/queries'
import { Dialog, EmptyState } from '../components/display'
import { Alert, Button, Input, Select } from '../components/ui'
import { cn } from '../lib/cn'
import { ConfigPanel } from './ConfigPanel'
import { DashboardView, type Breakpoint } from './DashboardView'
import {
  useDashboardActions,
  useDashboards,
  useLibrary,
  type Box,
  type Config,
  type Dashboard,
  type DashboardWidget,
  type Filters,
  type Layouts,
} from './api'

export const PERIODS = ['1D', '1W', '1M', '3M', 'YTD', '1Y', '3Y', '5Y', 'MAX'] as const

function AddWidgetDialog({
  onAdd,
  onClose,
}: {
  onAdd: (type: string) => void
  onClose: () => void
}) {
  const { t } = useTranslation()
  const library = useLibrary()
  return (
    <Dialog open onClose={onClose} title={t('dashboard.addWidget')} wide>
      <ul className="grid gap-2 sm:grid-cols-2">
        {library.data?.map((w) => (
          <li key={w.type}>
            <button
              type="button"
              onClick={() => onAdd(w.type)}
              className="w-full rounded-lg border border-border p-3 text-left hover:bg-border/30"
            >
              <span className="block font-medium">{t(`widgets.${w.type}`)}</span>
              <span className="block text-sm text-muted">{t(`widgetHelp.${w.type}`)}</span>
            </button>
          </li>
        ))}
      </ul>
    </Dialog>
  )
}

/** A dashboard on screen: its period and account filters, the grid, and edit mode (FR-DB-02,
 * FR-DB-03, FR-DB-05). Used for Home (the default dashboard) and for any dashboard by id. */
export function DashboardHost({ dashboard }: { dashboard: Dashboard }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const actions = useDashboardActions()
  const list = useDashboards()
  const accounts = useAccounts()
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
            onClick={() => void queryClient.invalidateQueries({ queryKey: ['widget-data'] })}
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
          <Link
            to="/dashboards"
            className="rounded-md border border-border px-3 py-2 text-sm hover:bg-border/40"
          >
            {t('dashboard.manage')}
          </Link>
        </div>
      </div>

      <div
        className="flex flex-wrap items-end gap-4"
        role="group"
        aria-label={t('dashboard.filters')}
      >
        <div role="group" aria-label={t('overview.periods.label')} className="flex flex-wrap gap-1">
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
            {!customReady && <p className="text-sm text-muted">{t('overview.customInvalid')}</p>}
          </div>
        )}
        {accounts.data && accounts.data.length > 1 && (
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
          onRemove={(w) => {
            if (window.confirm(t('dashboard.removeConfirm')))
              actions.removeWidget.mutate({ id: dashboard.id, widgetId: w.id })
          }}
        />
      )}

      {adding && (
        <AddWidgetDialog
          onClose={() => setAdding(false)}
          onAdd={(type) =>
            actions.addWidget.mutate(
              { id: dashboard.id, type },
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
