import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, unwrap } from '../api/client'
import type { components } from '../api/schema'

type S = components['schemas']
export type CalendarEvent = S['CalendarEventOut']
export type CalendarEventInput = S['CalendarEventIn']
export type CalendarEventChanges = S['CalendarEventChanges']

export const CALENDAR_KEY = ['calendar'] as const

export function useCalendarEvents(days = 90, pastDays = 7) {
  return useQuery({
    queryKey: [...CALENDAR_KEY, days, pastDays],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/calendar/events', { params: { query: { days, past_days: pastDays } } }),
      ),
  })
}

export function useSaveEvent() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id?: number; body: CalendarEventInput }) =>
      id === undefined
        ? unwrap(api.POST('/api/v1/calendar/events', { body }))
        : unwrap(
            api.PATCH('/api/v1/calendar/events/{event_id}', {
              params: { path: { event_id: id } },
              body: {
                title: body.title,
                date: body.date,
                detail: body.detail,
                instrument_id: body.instrument_id ?? null,
              },
            }),
          ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: CALENDAR_KEY }),
  })
}

export function useDeleteEvent() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      unwrap(
        api.DELETE('/api/v1/calendar/events/{event_id}', { params: { path: { event_id: id } } }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: CALENDAR_KEY }),
  })
}

export function useRefreshCalendar() {
  return useMutation({ mutationFn: () => unwrap(api.POST('/api/v1/calendar/refresh')) })
}
