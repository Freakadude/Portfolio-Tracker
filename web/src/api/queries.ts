import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, unwrap } from './client'
import type { components } from './schema'

type S = components['schemas']

export type Account = S['folio__api__routers__accounts__AccountOut']
export type Instrument = S['InstrumentOut']
export type Resolution = S['ResolutionOut']
export type Candidate = S['CandidateOut']
export type Position = S['PositionOut']
export type PositionsResponse = S['PositionsOut']
export type PositionDetail = S['PositionDetailOut']
export type Transaction = S['TransactionOut']
export type TransactionInput = S['TransactionIn']
export type SellPreview = S['SellPreviewOut']
export type AmountPreview = S['AmountPreviewOut']
export type Summary = S['SummaryOut']
export type CorporateAction = S['ActionOut']
export type ImportPreview = S['PreviewOut']
export type ImportBatch = S['BatchOut']
export type ImportMapping = S['ImportMapping']
export type DryRun = S['DryRunOut']
export type Usage = S['UsageOut']
export type JobsResponse = S['JobsOut']
export type AuditEntry = S['AuditOut']

/** After anything that changes the ledger or the instruments, refresh what depends on it. */
export function useInvalidateLedger() {
  const queryClient = useQueryClient()
  return () =>
    Promise.all(
      [
        'positions',
        'instruments',
        'transactions',
        'portfolio',
        'accounts',
        'corporate-actions',
        'drafts',
      ].map((key) => queryClient.invalidateQueries({ queryKey: [key] })),
    )
}

export function useAccounts() {
  return useQuery({
    queryKey: ['accounts'],
    queryFn: () => unwrap(api.GET('/api/v1/accounts')),
  })
}

export function useInstruments(status: 'active' | 'archived' | 'all' = 'active') {
  return useQuery({
    queryKey: ['instruments', status],
    queryFn: () => unwrap(api.GET('/api/v1/instruments', { params: { query: { status } } })),
  })
}

export interface PositionParams {
  account?: number
  includeClosed?: boolean
  asOf?: string
}

export function usePositions(p: PositionParams = {}) {
  return useQuery({
    queryKey: ['positions', p],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/positions', {
          params: { query: { account: p.account, include_closed: p.includeClosed, as_of: p.asOf } },
        }),
      ),
  })
}

export function usePositionDetail(instrumentId: number, account?: number) {
  return useQuery({
    queryKey: ['positions', 'detail', instrumentId, account],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/positions/{instrument_id}', {
          params: { path: { instrument_id: instrumentId }, query: { account } },
        }),
      ),
  })
}

export function usePrices(instrumentId: number) {
  return useQuery({
    queryKey: ['instruments', 'prices', instrumentId],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/instruments/{instrument_id}/prices', {
          params: { path: { instrument_id: instrumentId }, query: {} },
        }),
      ),
  })
}

export interface TransactionFilters {
  account?: number
  instrument?: number
  type?: string
  from?: string
  to?: string
  status?: 'posted' | 'draft' | 'all'
}

export function useTransactions(filters: TransactionFilters = {}, limit = 50) {
  return useInfiniteQuery({
    queryKey: ['transactions', filters, limit],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET('/api/v1/transactions', {
          params: { query: { ...filters, limit, cursor: pageParam } },
        }),
      ),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  })
}

export function useDrafts() {
  return useQuery({
    queryKey: ['drafts'],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/transactions', { params: { query: { status: 'draft', limit: 200 } } }),
      ),
  })
}

export function useCorporateActions(
  status: 'proposed' | 'applied' | 'dismissed' | 'all' = 'proposed',
) {
  return useQuery({
    queryKey: ['corporate-actions', status],
    queryFn: () => unwrap(api.GET('/api/v1/corporate-actions', { params: { query: { status } } })),
  })
}

export interface SummaryParams {
  period: string
  account?: number
  from?: string
  to?: string
}

export function usePortfolioSummary(p: SummaryParams) {
  return useQuery({
    queryKey: ['portfolio', 'summary', p],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/portfolio/summary', {
          params: { query: { period: p.period, account: p.account, from: p.from, to: p.to } },
        }),
      ),
  })
}

export function useSystemUsage() {
  return useQuery({
    queryKey: ['system', 'usage'],
    queryFn: () => unwrap(api.GET('/api/v1/system/usage')),
    refetchInterval: 15_000,
  })
}

export function useJobs() {
  return useQuery({
    queryKey: ['system', 'jobs'],
    queryFn: () => unwrap(api.GET('/api/v1/system/jobs', { params: { query: { limit: 30 } } })),
    refetchInterval: 5_000, // the worker picks requests up within seconds
  })
}

export interface AuditFilters {
  entity?: string
  actor?: string
  action?: string
  from?: string
  to?: string
}

export function useAudit(filters: AuditFilters = {}) {
  return useInfiniteQuery({
    queryKey: ['system', 'audit', filters],
    initialPageParam: undefined as number | undefined,
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET('/api/v1/audit', {
          params: { query: { ...filters, limit: 50, cursor: pageParam } },
        }),
      ),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  })
}
