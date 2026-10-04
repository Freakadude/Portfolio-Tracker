import { useQuery } from '@tanstack/react-query'
import { api, unwrap } from '../api/client'
import { formatEur, formatNumber, formatPercent, formatQuantity, type NumberFormat } from './format'

/** The owner's number format (Settings > General), with formatters bound to it. */
export function useFormat() {
  const { data } = useQuery({
    queryKey: ['settings', 'general'],
    queryFn: () =>
      unwrap(api.GET('/api/v1/settings/{section}', { params: { path: { section: 'general' } } })),
    staleTime: 60_000,
  })
  const format: NumberFormat =
    (data as { number_format?: string } | undefined)?.number_format === 'us' ? 'us' : 'eu'
  return {
    format,
    eur: (v: string | number | null | undefined, decimals = 2) => formatEur(v, format, decimals),
    num: (v: string | number | null | undefined, decimals = 2) => formatNumber(v, format, decimals),
    qty: (v: string | number | null | undefined) => formatQuantity(v, format),
    pct: (v: string | number | null | undefined, decimals = 2) =>
      formatPercent(v, format, decimals),
  }
}
