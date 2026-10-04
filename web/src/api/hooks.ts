import { useQuery } from '@tanstack/react-query'
import { api, unwrap } from './client'

export const STATUS_KEY = ['setup-status'] as const

export function useSetupStatus() {
  return useQuery({
    queryKey: STATUS_KEY,
    queryFn: () => unwrap(api.GET('/api/v1/setup/status')),
    staleTime: 10_000,
  })
}
