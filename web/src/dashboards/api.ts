import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, unwrap } from '../api/client'
import type { components } from '../api/schema'

type S = components['schemas']

export type Dashboard = S['DashboardOut']
export type DashboardSummary = S['DashboardSummary']
export type DashboardWidget = S['WidgetOut']
export type LibraryEntry = S['LibraryEntry']
export type Template = S['TemplateOut']
export type Box = { i: string; x: number; y: number; w: number; h: number }
export type Layouts = Record<string, Box[]>
export type Config = Record<string, unknown>

export interface Filters {
  period?: string | null
  account?: number | null
  start?: string | null // for the custom period
  end?: string | null
}

export interface WidgetRequest {
  key: string
  type: string
  config: Config
}

export interface WidgetResult {
  data?: Record<string, unknown> | null
  error?: string | null
}

export const dashboardKey = (id: number | 'default') => ['dashboards', id] as const

export function useDefaultDashboard() {
  return useQuery({
    queryKey: dashboardKey('default'),
    queryFn: () => unwrap(api.GET('/api/v1/dashboards/default')),
  })
}

export function useDashboard(id: number) {
  return useQuery({
    queryKey: dashboardKey(id),
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/dashboards/{dashboard_id}', { params: { path: { dashboard_id: id } } }),
      ),
  })
}

export function useDashboards() {
  return useQuery({
    queryKey: ['dashboards', 'list'],
    queryFn: () => unwrap(api.GET('/api/v1/dashboards')),
  })
}

export function useTemplates() {
  return useQuery({
    queryKey: ['dashboard-templates'],
    queryFn: () => unwrap(api.GET('/api/v1/dashboard-templates')),
    staleTime: Infinity,
  })
}

export function useLibrary() {
  return useQuery({
    queryKey: ['dashboard-library'],
    queryFn: () => unwrap(api.GET('/api/v1/dashboard-widgets')),
    staleTime: Infinity,
  })
}

/** What the browser asks for when many widgets are on screen: one request for all of them. */
export function useWidgetData(requests: WidgetRequest[], filters: Filters) {
  return useQuery({
    queryKey: ['widget-data', requests, filters],
    enabled: requests.length > 0,
    // Keep the previous picture on screen while new data loads, so nothing flashes or jumps.
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const out = await unwrap(
        api.POST('/api/v1/widgets/data', {
          body: {
            requests,
            filters: {
              period: filters.period ?? null,
              account: filters.account ?? null,
              start: filters.period === 'CUSTOM' ? (filters.start ?? null) : null,
              end: filters.period === 'CUSTOM' ? (filters.end ?? null) : null,
            },
          },
        }),
      )
      return out.results as Record<string, WidgetResult>
    },
  })
}

/** Everything that changes a dashboard, refreshing the lists and the open dashboard after. */
export function useDashboardActions() {
  const queryClient = useQueryClient()
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['dashboards'] })
  const settle = (dashboard: Dashboard) => {
    queryClient.setQueryData(dashboardKey(dashboard.id), dashboard)
    void refresh()
    return dashboard
  }
  return {
    create: useMutation({
      mutationFn: (b: { name: string; template?: string | null }) =>
        unwrap(api.POST('/api/v1/dashboards', { body: b })).then(settle),
    }),
    rename: useMutation({
      mutationFn: (b: { id: number; name: string }) =>
        unwrap(
          api.PATCH('/api/v1/dashboards/{dashboard_id}', {
            params: { path: { dashboard_id: b.id } },
            body: { name: b.name },
          }),
        ).then(settle),
    }),
    setFilters: useMutation({
      mutationFn: (b: { id: number; filters: Filters }) =>
        unwrap(
          api.PATCH('/api/v1/dashboards/{dashboard_id}', {
            params: { path: { dashboard_id: b.id } },
            body: { filters: b.filters as Record<string, unknown> },
          }),
        ).then(settle),
    }),
    remove: useMutation({
      mutationFn: (id: number) =>
        unwrap(
          api.DELETE('/api/v1/dashboards/{dashboard_id}', {
            params: { path: { dashboard_id: id } },
          }),
        ).then(refresh),
    }),
    duplicate: useMutation({
      mutationFn: (id: number) =>
        unwrap(
          api.POST('/api/v1/dashboards/{dashboard_id}/duplicate', {
            params: { path: { dashboard_id: id } },
          }),
        ).then(settle),
    }),
    makeDefault: useMutation({
      mutationFn: (id: number) =>
        unwrap(
          api.POST('/api/v1/dashboards/{dashboard_id}/default', {
            params: { path: { dashboard_id: id } },
          }),
        ).then(settle),
    }),
    reorder: useMutation({
      mutationFn: (ids: number[]) =>
        unwrap(api.PUT('/api/v1/dashboards/order', { body: { ids } })).then(refresh),
    }),
    saveLayout: useMutation({
      mutationFn: (b: { id: number; layouts: Layouts }) =>
        unwrap(
          api.PUT('/api/v1/dashboards/{dashboard_id}/layout', {
            params: { path: { dashboard_id: b.id } },
            body: { layouts: b.layouts },
          }),
        ).then(settle),
    }),
    addWidget: useMutation({
      mutationFn: (b: { id: number; type: string; config?: Config }) =>
        unwrap(
          api.POST('/api/v1/dashboards/{dashboard_id}/widgets', {
            params: { path: { dashboard_id: b.id } },
            body: { type: b.type, config: b.config ?? {} },
          }),
        ).then(settle),
    }),
    updateWidget: useMutation({
      mutationFn: (b: { id: number; widgetId: number; config: Config }) =>
        unwrap(
          api.PATCH('/api/v1/dashboards/{dashboard_id}/widgets/{widget_id}', {
            params: { path: { dashboard_id: b.id, widget_id: b.widgetId } },
            body: { config: b.config },
          }),
        ).then(settle),
    }),
    removeWidget: useMutation({
      mutationFn: (b: { id: number; widgetId: number }) =>
        unwrap(
          api.DELETE('/api/v1/dashboards/{dashboard_id}/widgets/{widget_id}', {
            params: { path: { dashboard_id: b.id, widget_id: b.widgetId } },
          }),
        ).then(settle),
    }),
    importDocument: useMutation({
      mutationFn: (document: Record<string, unknown>) =>
        unwrap(api.POST('/api/v1/dashboards/import', { body: { document } })).then(settle),
    }),
  }
}

export async function exportDashboard(id: number): Promise<Record<string, unknown>> {
  return (await unwrap(
    api.GET('/api/v1/dashboards/{dashboard_id}/export', { params: { path: { dashboard_id: id } } }),
  )) as Record<string, unknown>
}

export type Sleeve = S['SleeveOut']

export function useSleeves() {
  return useQuery({
    queryKey: ['sleeves'],
    queryFn: () => unwrap(api.GET('/api/v1/sleeves')),
  })
}
