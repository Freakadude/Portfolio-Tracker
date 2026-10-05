import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, unwrap } from '../api/client'
import type { components } from '../api/schema'

type S = components['schemas']
export type Notification = S['NotificationOut']
export type Delivery = S['DeliveryOut']
export type PriceAlert = S['AlertOut']
export type MacroSeries = S['folio__api__routers__macro__SeriesOut']

export const NOTIFY_KEY = ['notifications'] as const

export interface InboxFilters {
  severity?: string
  source?: string
  status?: 'unread' | 'read' | 'all'
  subject?: string
}

export function useUnread() {
  return useQuery({
    queryKey: [...NOTIFY_KEY, 'unread'],
    queryFn: () => unwrap(api.GET('/api/v1/notifications/unread')),
  })
}

export function useInbox(filters: InboxFilters) {
  return useQuery({
    queryKey: [...NOTIFY_KEY, 'inbox', filters],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/notifications', {
          params: {
            query: {
              severity: filters.severity || undefined,
              source: filters.source || undefined,
              status: filters.status ?? 'all',
              subject: filters.subject || undefined,
              limit: 100,
            },
          },
        }),
      ),
  })
}

export function useDeliveries() {
  return useQuery({
    queryKey: [...NOTIFY_KEY, 'deliveries'],
    queryFn: () =>
      unwrap(api.GET('/api/v1/notifications/deliveries', { params: { query: { limit: 20 } } })),
  })
}

export function useMarkRead() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { ids?: number[]; all?: boolean; read?: boolean }) =>
      unwrap(
        api.POST('/api/v1/notifications/read', {
          body: { ids: body.ids ?? [], all: body.all ?? false, read: body.read ?? true },
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: NOTIFY_KEY }),
  })
}

export function useMacroSeries() {
  return useQuery({
    queryKey: ['macro', 'series'],
    queryFn: () => unwrap(api.GET('/api/v1/macro/series')),
  })
}

export function useAlerts(instrumentId?: number) {
  return useQuery({
    queryKey: ['price-alerts', instrumentId ?? 'all'],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/price-alerts', {
          params: { query: { instrument_id: instrumentId } },
        }),
      ),
  })
}
