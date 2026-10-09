import type { Config, Filters } from './api'

/** What every widget component receives. `data` is the server's answer for its options. */
export interface WidgetProps<D = Record<string, unknown>> {
  data: D
  config: Config
  filters: Filters
}

export interface Empty {
  empty?: true
  reason?: string
}

/** The steps behind a time-weighted return or an XIRR ("how is this calculated"). */
export type ReturnBreakdownData =
  | {
      kind: 'twr'
      segments: {
        start: string
        end: string
        flow: string
        start_capital: string
        end_value: string
        income: string
        ratio: string
      }[]
    }
  | { kind: 'xirr'; flows: { date: string; amount: string; kind: string }[] }

export interface KpiData extends Empty {
  metric: string
  kind: 'eur' | 'pct' | 'number'
  value: string | null
  change_eur?: string | null
  change_ratio?: string | null
  label?: string
  note?: string
  sparkline: { date: string; value: string }[]
  as_of?: string
  start?: string
  end?: string
  breakdown?: ReturnBreakdownData
}

export interface ValueHistoryData extends Empty {
  points?: { date: string; value: string; net_contributions: string }[]
  log_scale?: boolean
  period?: string
  start?: string
  end?: string
  unpriced_before?: string | null
  unpriced_days?: number
}

export interface DrawdownData extends Empty {
  points?: { date: string; value: string }[]
  max_drawdown?: string
  current_drawdown?: string
  max_start?: string | null
  max_end?: string | null
}

export interface MonthlyData extends Empty {
  years?: { year: number; months: Record<string, string>; total: string }[]
}

export interface AllocationData extends Empty {
  unavailable?: true
  group_by?: string
  chart?: 'donut' | 'treemap'
  show_target?: boolean
  total_eur?: string
  unvalued?: number
  slices?: {
    key: string
    value_eur: string
    weight: string
    target: string | null
    drift_pp: string | null
    outside_band: boolean | null
    parts?: ExposurePart[]
  }[]
  look_through?: boolean
  unopened?: string[]
}

/** Where part of a look-through exposure sits: held directly, or inside an ETF. */
export interface ExposurePart {
  source: string
  instrument_id: number
  kind: 'direct' | 'look_through' | 'fund' | 'other'
  value_eur: string
  weight_pct: string | null
}

export interface LookThroughData extends Empty {
  dimension?: 'company' | 'sector' | 'country' | 'currency'
  total_eur?: string
  slices?: {
    key: string
    value_eur: string
    weight: string
    other: boolean
    parts: ExposurePart[]
  }[]
  rest_weight?: string
  opened?: { name: string; holdings_as_of: string }[]
  unopened?: string[]
  unvalued?: number
}

export interface DriftData extends Empty {
  bars?: {
    key: string
    weight: string
    target: string
    drift_pp: string
    band: string | null
    outside_band: boolean | null
  }[]
}

export interface HoldingsData extends Empty {
  columns?: string[]
  group_by?: 'none' | 'account' | 'sleeve' | 'asset_class'
  sort_by?: string | null
  sort_dir?: 'asc' | 'desc'
  rows?: {
    instrument_id: number
    name: string
    account: string
    asset_class: string
    sleeve: string | null
    quantity: string
    close: string | null
    close_date: string | null
    latest: string | null
    latest_at: string | null
    target_weight: string | null
    weight_diff: string | null
    stale: boolean
    value: string | null
    weight: string | null
    unrealized: string | null
    unrealized_ratio: string | null
    day: string | null
    day_ratio: string | null
    total_return: string | null
    income: string
  }[]
  totals?: {
    value: string
    unrealized: string
    unrealized_ratio: string | null
    day: string | null
    income: string
  }
}

export interface HeatmapData extends Empty {
  start?: string
  end?: string
  cells?: {
    instrument_id: number
    name: string
    twr: string | null
    pnl_eur: string
    value_eur: string
  }[]
}

export interface CorrelationData extends Empty {
  window?: string
  instruments?: { id: number; name: string }[]
  values?: (string | null)[][]
}

export interface BridgeData extends Empty {
  start?: string
  end?: string
  steps?: { label: string; amount_eur: string; kind: 'total' | 'delta' }[]
}

export interface AttributionData extends Empty {
  start?: string
  end?: string
  portfolio_pnl_eur?: string
  total_return?: string | null
  rows?: { key: string; name: string; pnl_eur: string; points: string | null }[]
}

export interface IncomeData extends Empty {
  months?: { month: string; dividends: string; interest: string }[]
  total_eur?: string
}

export interface MacroData extends Empty {
  start?: string
  end?: string
  panes?: { code: string; name: string; unit: string; points: { date: string; value: string }[] }[]
  instrument?: { id: number; name: string; points: { date: string; value: string }[] }
}

export interface PriceChartData extends Empty {
  instrument_id?: number
  name?: string
  currency?: string
  chart?: 'line' | 'candles'
  /** One day of refresh prices; each point's date is the exchange clock, 2024-01-12T09:15:00. */
  intraday?: boolean
  session_date?: string
  previous_close?: string | null
  /** False when only the changes are shown. */
  show_price?: boolean
  changes?: { date: string; value: string }[]
  since_start?: { date: string; value: string }[]
  points?: {
    date: string
    open: string | null
    high: string | null
    low: string | null
    close: string
    volume: string | null
  }[]
  ma50?: { date: string; value: string }[]
  ma200?: { date: string; value: string }[]
  trades?: { date: string; type: string; quantity: string; price: string }[]
}

export interface PerformanceData extends Empty {
  suggest_benchmark?: boolean
  start?: string
  end?: string
  series?: { key: string; label: string; points: { date: string; value: string }[] }[]
}

export interface Unavailable {
  unavailable?: true
  reason?: string
}
