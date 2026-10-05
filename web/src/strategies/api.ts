import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiProblem, api, unwrap } from '../api/client'
import type { components } from '../api/schema'

type S = components['schemas']
export type StrategySummary = S['StrategySummary']
export type Strategy = S['StrategyOut']
export type Problem = S['ProblemOut']
export type Signal = S['SignalOut']
export type Status = S['StatusOut']
export type Plan = S['PlanOut']
export type Order = S['OrderOut']
export type Diff = S['DiffOut']
export type Definition = Record<string, unknown>

export const KEY = ['strategies'] as const

export function useStrategies() {
  return useQuery({ queryKey: KEY, queryFn: () => unwrap(api.GET('/api/v1/strategies')) })
}

export function useStrategy(id: number | null) {
  return useQuery({
    queryKey: [...KEY, id],
    enabled: id !== null,
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/strategies/{strategy_id}', {
          params: { path: { strategy_id: id ?? 0 } },
        }),
      ),
  })
}

export function useStatus(id: number) {
  return useQuery({
    queryKey: [...KEY, id, 'status'],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/strategies/{strategy_id}/status', {
          params: { path: { strategy_id: id } },
        }),
      ),
  })
}

export function useSignals(strategyId: number) {
  return useQuery({
    queryKey: [...KEY, strategyId, 'signals'],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/strategies/signals', {
          params: { query: { strategy_id: strategyId, limit: 50 } },
        }),
      ),
  })
}

export function useDiff(id: number, oldVersion: number | null, newVersion: number | null) {
  return useQuery({
    queryKey: [...KEY, id, 'diff', oldVersion, newVersion],
    enabled: oldVersion !== null && newVersion !== null && oldVersion !== newVersion,
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/strategies/{strategy_id}/diff', {
          params: {
            path: { strategy_id: id },
            query: { old: oldVersion ?? 0, new: newVersion ?? 0 },
          },
        }),
      ),
  })
}

/** The line-numbered problems the API sends with a 422 for an invalid strategy. */
export function problemsOf(error: unknown): Problem[] {
  if (error instanceof ApiProblem && Array.isArray(error.extra.problems)) {
    return error.extra.problems as Problem[]
  }
  return []
}

export function useInvalidateStrategies() {
  const queryClient = useQueryClient()
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: KEY }),
      queryClient.invalidateQueries({ queryKey: ['sleeves'] }),
    ])
}

export function useCheck() {
  return useMutation({
    mutationFn: (body: { yaml: string } | { definition: Definition }) =>
      unwrap(api.POST('/api/v1/strategies/check', { body })),
  })
}
