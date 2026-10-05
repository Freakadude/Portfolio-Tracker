import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, unwrap } from '../api/client'
import type { components } from '../api/schema'

type S = components['schemas']
export type NewsCluster = S['NewsClusterOut']
export type NewsSource = S['SourceOut']
export type NewsSourceInput = S['SourceIn']
export type FeedPreview = S['FeedPreviewOut']

export const NEWS_KEY = ['news'] as const

export interface NewsFilters {
  instrument?: number
  minImpact?: number
  direction?: string
  source?: number
  from?: string
  to?: string
  includeUnlinked?: boolean
  sort?: 'time' | 'relevance' | 'impact'
  limit?: number
}

export function useNews(f: NewsFilters) {
  return useQuery({
    queryKey: [...NEWS_KEY, 'list', f],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/news', {
          params: {
            query: {
              instrument: f.instrument,
              min_impact: f.minImpact || undefined,
              direction: f.direction || undefined,
              source: f.source,
              from: f.from || undefined,
              to: f.to || undefined,
              include_unlinked: f.includeUnlinked || undefined,
              sort: f.sort ?? 'time',
              limit: f.limit ?? 30,
            },
          },
        }),
      ),
  })
}

export function useNewsSources() {
  return useQuery({
    queryKey: [...NEWS_KEY, 'sources'],
    queryFn: () => unwrap(api.GET('/api/v1/news/sources')),
  })
}

export function useSaveNewsSource() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id?: number; body: NewsSourceInput }) =>
      id === undefined
        ? unwrap(api.POST('/api/v1/news/sources', { body }))
        : unwrap(
            api.PUT('/api/v1/news/sources/{source_id}', {
              params: { path: { source_id: id } },
              body,
            }),
          ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: NEWS_KEY }),
  })
}

export function useDeleteNewsSource() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      unwrap(
        api.DELETE('/api/v1/news/sources/{source_id}', { params: { path: { source_id: id } } }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: NEWS_KEY }),
  })
}

export function usePreviewFeed() {
  return useMutation({
    mutationFn: (url: string) =>
      unwrap(api.POST('/api/v1/news/sources/preview', { body: { url } })),
  })
}

export function useFetchNow() {
  return useMutation({
    mutationFn: (id: number) =>
      unwrap(
        api.POST('/api/v1/news/sources/{source_id}/fetch', {
          params: { path: { source_id: id } },
        }),
      ),
  })
}

export function useNewsFeedback() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      id,
      verdict,
      linkId,
    }: {
      id: number
      verdict: 'useful' | 'not_relevant'
      linkId?: number
    }) =>
      unwrap(
        api.POST('/api/v1/news/clusters/{cluster_id}/feedback', {
          params: { path: { cluster_id: id } },
          body: { verdict, link_id: linkId ?? null },
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: NEWS_KEY }),
  })
}
