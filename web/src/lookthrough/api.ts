import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, unwrap } from '../api/client'
import type { components } from '../api/schema'

type S = components['schemas']
export type HoldingsView = S['HoldingsOut']
export type HoldingsPreview = S['HoldingsPreviewOut']
export type HoldingsMapping = S['HoldingsMapping']
export type HoldingsSource = S['HoldingsSource']

export const holdingsKey = (id: number) => ['etf-holdings', id] as const

export function useHoldings(instrumentId: number) {
  return useQuery({
    queryKey: holdingsKey(instrumentId),
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/instruments/{instrument_id}/holdings', {
          params: { path: { instrument_id: instrumentId } },
        }),
      ),
  })
}

function form(file: File, mapping?: HoldingsMapping, asOf?: string, sheet?: string) {
  const data = new FormData()
  data.set('file', file)
  if (sheet) data.set('sheet', sheet)
  if (mapping) data.set('mapping', JSON.stringify(mapping))
  if (asOf) data.set('as_of', asOf)
  return data
}

export function usePreviewHoldings(instrumentId: number) {
  return useMutation({
    mutationFn: ({
      file,
      mapping,
      sheet,
    }: {
      file: File
      mapping?: HoldingsMapping
      sheet?: string
    }) =>
      unwrap(
        api.POST('/api/v1/instruments/{instrument_id}/holdings/preview', {
          params: { path: { instrument_id: instrumentId } },
          body: {} as never,
          bodySerializer: () => form(file, mapping, undefined, sheet),
        }),
      ),
  })
}

export function useStoreHoldings(instrumentId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      file,
      mapping,
      asOf,
    }: {
      file: File
      mapping?: HoldingsMapping
      asOf?: string
    }) =>
      unwrap(
        api.POST('/api/v1/instruments/{instrument_id}/holdings', {
          params: { path: { instrument_id: instrumentId } },
          body: {} as never,
          bodySerializer: () => form(file, mapping, asOf),
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: holdingsKey(instrumentId) })
      void queryClient.invalidateQueries({ queryKey: ['dashboards'] })
    },
  })
}

export function useDeleteSnapshot(instrumentId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (snapshotId: number) =>
      unwrap(
        api.DELETE('/api/v1/instruments/{instrument_id}/holdings/{snapshot_id}', {
          params: { path: { instrument_id: instrumentId, snapshot_id: snapshotId } },
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: holdingsKey(instrumentId) }),
  })
}

export function useSaveSource(instrumentId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: HoldingsSource) =>
      unwrap(
        api.PUT('/api/v1/instruments/{instrument_id}/holdings/source', {
          params: { path: { instrument_id: instrumentId } },
          body,
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: holdingsKey(instrumentId) }),
  })
}

export function useRefreshHoldings(instrumentId: number) {
  return useMutation({
    mutationFn: () =>
      unwrap(
        api.POST('/api/v1/instruments/{instrument_id}/holdings/refresh', {
          params: { path: { instrument_id: instrumentId } },
        }),
      ),
  })
}
