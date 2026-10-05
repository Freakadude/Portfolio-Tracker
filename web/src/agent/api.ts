import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, unwrap } from '../api/client'
import type { components } from '../api/schema'

type S = components['schemas']
export type Recommendation = S['RecommendationOut']
export type RecommendationDetail = S['RecommendationDetailOut']
export type AgentBudget = S['AgentBudgetOut']
export type AgentRun = S['AgentRunOut']
export type AgentRunDetail = S['AgentRunDetailOut']

export const REC_KEY = ['recommendations'] as const
export const AGENT_KEY = ['agent'] as const

export type RecStatus = 'open' | 'accepted' | 'rejected' | 'snoozed' | 'expired'

export function useRecommendations(status: RecStatus) {
  return useQuery({
    queryKey: [...REC_KEY, 'list', status],
    queryFn: () =>
      unwrap(api.GET('/api/v1/recommendations', { params: { query: { status, limit: 50 } } })),
  })
}

export function useRecommendation(id: number) {
  return useQuery({
    queryKey: [...REC_KEY, 'one', id],
    queryFn: () =>
      unwrap(api.GET('/api/v1/recommendations/{rec_id}', { params: { path: { rec_id: id } } })),
  })
}

export function useDecide() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      id,
      action,
      note,
      days,
      createDrafts,
    }: {
      id: number
      action: 'seen' | 'accept' | 'reject' | 'snooze'
      note?: string
      days?: number
      createDrafts?: boolean
    }) =>
      unwrap(
        api.PATCH('/api/v1/recommendations/{rec_id}', {
          params: { path: { rec_id: id } },
          body: {
            action,
            note: note || null,
            days: days ?? null,
            create_drafts: createDrafts ?? false,
          },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: REC_KEY })
      void queryClient.invalidateQueries({ queryKey: ['drafts'] })
      void queryClient.invalidateQueries({ queryKey: ['widget-data'] })
    },
  })
}

export function useAgentBudget() {
  return useQuery({
    queryKey: [...AGENT_KEY, 'usage'],
    queryFn: () => unwrap(api.GET('/api/v1/agent/usage')),
  })
}

export function useAgentRuns() {
  return useQuery({
    queryKey: [...AGENT_KEY, 'runs'],
    queryFn: () => unwrap(api.GET('/api/v1/agent/runs', { params: { query: { limit: 30 } } })),
  })
}

export function useAgentRun(id: number | null) {
  return useQuery({
    queryKey: [...AGENT_KEY, 'run', id],
    enabled: id !== null,
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/agent/runs/{run_id}', { params: { path: { run_id: id as number } } }),
      ),
  })
}

export function useRunNow() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { runType: 'daily_review' | 'on_demand'; question?: string }) =>
      unwrap(
        api.POST('/api/v1/agent/runs', {
          body: { run_type: body.runType, question: body.question || null },
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: AGENT_KEY }),
  })
}

export function useTestKey() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/agent/test')),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: AGENT_KEY }),
  })
}
