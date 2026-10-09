import type { ComponentType } from 'react'
import type { WidgetProps } from './types'
import { AllocationWidget, DriftBarsWidget, HoldingsTableWidget } from './widgets/Composition'
import {
  DrawdownWidget,
  PerformanceWidget,
  PriceChartWidget,
  PriceHistoryWidget,
  ValueHistoryWidget,
} from './widgets/History'
import { KpiWidget } from './widgets/Kpi'
import { AskWidget, NewsFeedWidget, SignalsWidget } from './widgets/Feeds'
import { ProjectionWidget } from './widgets/Projection'
import { LookThroughWidget } from './widgets/LookThrough'
import { MacroWidget } from './widgets/Macro'
import {
  AttributionWidget,
  BridgeWidget,
  CorrelationWidget,
  HeatmapWidget,
  IncomeWidget,
  MonthlyReturnsWidget,
} from './widgets/Returns'
import { NoteWidget } from './widgets/Simple'

export type ScopeKind = 'portfolio' | 'account' | 'sleeve' | 'instrument'

/** One option the side panel can edit, beyond the common ones (title, scope, period). */
export interface OptionField {
  key: string
  kind:
    | 'select'
    | 'boolean'
    | 'number'
    | 'longtext'
    | 'instrument'
    | 'instruments'
    | 'multi'
    | 'ordered'
    | 'sortby'
    | 'macro'
  options?: readonly string[]
  /** What a widget shows until the owner chooses (the server has the same default). */
  fallback?: readonly string[]
  /** i18n prefix for the option labels: `${labels}.${option}` */
  labels?: string
  min?: number
  max?: number
}

export interface WidgetDef {
  type: string
  Component: ComponentType<WidgetProps<Record<string, unknown>>>
  /** Draws a chart: every chart has a drill-down and a table view (FR-DB-06, NFR-11). */
  chart: boolean
  /** Where a click on an element of the chart leads, for the tests and the documentation. */
  drillsTo: string
  scopes: readonly ScopeKind[]
  period: boolean
  fields: readonly OptionField[]
}

function def<D>(
  Component: ComponentType<WidgetProps<D>>,
  rest: Omit<WidgetDef, 'Component' | 'type'>,
): Omit<WidgetDef, 'type'> {
  return { Component: Component as unknown as WidgetDef['Component'], ...rest }
}

const PORTFOLIO_ACCOUNT = ['portfolio', 'account'] as const
const ALL_SCOPES = ['portfolio', 'account', 'sleeve', 'instrument'] as const
const GROUPS = [
  'instrument',
  'asset_class',
  'sleeve',
  'region',
  'sector',
  'currency',
  'company',
  'country',
] as const
export const KPI_METRICS = [
  'value',
  'day_change',
  'total_return',
  'unrealized',
  'realized',
  'period_return',
  'twr',
  'xirr',
  'cash',
  'net_contributions',
  'income',
  'largest_drift',
  'volatility',
  'max_drawdown',
  'current_drawdown',
  'sharpe',
  'beta',
  'latest_price',
] as const // fmt: skip

const DEFS: Record<string, Omit<WidgetDef, 'type'>> = {
  kpi: def(KpiWidget, {
    chart: false,
    drillsTo: 'holdings, reports or dashboards, by metric',
    scopes: ALL_SCOPES,
    period: true,
    fields: [
      { key: 'metric', kind: 'select', options: KPI_METRICS, labels: 'widgets.metrics' },
      { key: 'sparkline', kind: 'boolean' },
    ],
  }),
  value_history: def(ValueHistoryWidget, {
    chart: true,
    drillsTo: 'transactions up to the clicked date',
    scopes: ALL_SCOPES,
    period: true,
    fields: [{ key: 'log_scale', kind: 'boolean' }],
  }),
  price_chart: def(PriceChartWidget, {
    chart: true,
    drillsTo: 'the position page',
    scopes: ['portfolio'],
    period: true,
    fields: [
      { key: 'instrument_id', kind: 'instrument' },
      { key: 'chart', kind: 'select', options: ['line', 'candles'], labels: 'widgets.chartTypes' },
      {
        key: 'overlays',
        kind: 'multi',
        options: ['price', 'trades', 'ma50', 'ma200', 'volume', 'changes', 'since_start'],
        labels: 'widgets.overlays',
      },
    ],
  }),
  price_history: def(PriceHistoryWidget, {
    chart: true,
    drillsTo: 'the position page',
    scopes: ['portfolio'],
    period: true,
    fields: [{ key: 'instrument_ids', kind: 'instruments' }],
  }),
  performance_comparison: def(PerformanceWidget, {
    chart: true,
    drillsTo: 'transactions up to the clicked date',
    scopes: PORTFOLIO_ACCOUNT,
    period: true,
    fields: [],
  }),
  allocation: def(AllocationWidget, {
    chart: true,
    drillsTo: 'the holdings list filtered to the slice',
    scopes: PORTFOLIO_ACCOUNT,
    period: false,
    fields: [
      { key: 'group_by', kind: 'select', options: GROUPS, labels: 'widgets.groups' },
      { key: 'chart', kind: 'select', options: ['donut', 'treemap'], labels: 'widgets.chartTypes' },
      { key: 'show_target', kind: 'boolean' },
      { key: 'look_through', kind: 'boolean' },
    ],
  }),
  drift_bars: def(DriftBarsWidget, {
    chart: true,
    drillsTo: 'the holdings list filtered to the sleeve',
    scopes: PORTFOLIO_ACCOUNT,
    period: false,
    fields: [],
  }),
  holdings_table: def(HoldingsTableWidget, {
    chart: false,
    drillsTo: 'the position page',
    scopes: PORTFOLIO_ACCOUNT,
    period: false,
    fields: [
      {
        key: 'group_by',
        kind: 'select',
        options: ['none', 'sleeve', 'asset_class'],
        labels: 'widgets.tableGroups',
      },
      {
        key: 'columns',
        kind: 'ordered',
        fallback: ['name', 'quantity', 'value', 'weight', 'unrealized', 'day'],
        options: [
          'name',
          'quantity',
          'close',
          'latest',
          'value',
          'weight',
          'target_weight',
          'weight_diff',
          'unrealized',
          'day',
          'income',
          'total_return',
        ],
        labels: 'widgets.columns',
      },
      { key: 'sort_by', kind: 'sortby', labels: 'widgets.columns' },
      {
        key: 'sort_dir',
        kind: 'select',
        options: ['desc', 'asc'],
        labels: 'widgets.sortDirs',
      },
    ],
  }),
  returns_heatmap: def(HeatmapWidget, {
    chart: true,
    drillsTo: 'the position page',
    scopes: PORTFOLIO_ACCOUNT,
    period: true,
    fields: [],
  }),
  monthly_returns: def(MonthlyReturnsWidget, {
    chart: true,
    drillsTo: 'transactions of the clicked month',
    scopes: ALL_SCOPES,
    period: false,
    fields: [],
  }),
  look_through: def(LookThroughWidget, {
    chart: true,
    drillsTo: 'the position page of the position that holds it',
    scopes: PORTFOLIO_ACCOUNT,
    period: false,
    fields: [
      {
        key: 'dimension',
        kind: 'select',
        options: ['company', 'sector', 'country', 'currency'],
        labels: 'lookThrough.dimension',
      },
      { key: 'top_n', kind: 'number', min: 1, max: 100 },
    ],
  }),
  correlation_matrix: def(CorrelationWidget, {
    chart: true,
    drillsTo: 'the position page',
    scopes: PORTFOLIO_ACCOUNT,
    period: false,
    fields: [{ key: 'window', kind: 'select', options: ['90D', '1Y'], labels: 'widgets.windows' }],
  }),
  drawdown: def(DrawdownWidget, {
    chart: true,
    drillsTo: 'transactions up to the clicked date',
    scopes: ALL_SCOPES,
    period: true,
    fields: [],
  }),
  return_bridge: def(BridgeWidget, {
    chart: true,
    drillsTo: 'the holdings list filtered to the position, or transactions',
    scopes: PORTFOLIO_ACCOUNT,
    period: true,
    fields: [],
  }),
  attribution: def(AttributionWidget, {
    chart: true,
    drillsTo: 'the holdings list filtered to the position',
    scopes: PORTFOLIO_ACCOUNT,
    period: true,
    fields: [],
  }),
  income: def(IncomeWidget, {
    chart: true,
    drillsTo: 'transactions of the clicked month',
    scopes: PORTFOLIO_ACCOUNT,
    period: true,
    fields: [],
  }),
  macro_overlay: def(MacroWidget, {
    chart: true,
    drillsTo: 'the macro series list in Settings',
    scopes: ['portfolio'],
    period: true,
    fields: [
      { key: 'series_code', kind: 'macro' },
      { key: 'second_code', kind: 'macro' },
      { key: 'instrument_id', kind: 'instrument' },
    ],
  }),
  news_feed: def(NewsFeedWidget, {
    chart: false,
    drillsTo: 'the story on the News page',
    scopes: ['portfolio'],
    period: false,
    fields: [{ key: 'min_impact', kind: 'number', min: 0, max: 100 }],
  }),
  signals: def(SignalsWidget, {
    chart: false,
    drillsTo: 'the recommendation on Insights, or the strategy',
    scopes: ['portfolio'],
    period: false,
    fields: [
      {
        key: 'severity',
        kind: 'select',
        options: ['all', 'low', 'medium', 'high', 'critical'],
        labels: 'recs.severity',
      },
    ],
  }),
  projection: def(ProjectionWidget, {
    chart: true,
    drillsTo: 'the projection on the Reports page',
    scopes: PORTFOLIO_ACCOUNT,
    period: false,
    fields: [
      { key: 'years', kind: 'number', min: 1, max: 40 },
      { key: 'monthly_contribution', kind: 'number', min: 0, max: 1000000 },
      { key: 'return_pct', kind: 'number', min: -50, max: 50 },
      { key: 'volatility_pct', kind: 'number', min: 0, max: 100 },
    ],
  }),
  ask: def(AskWidget, {
    chart: false,
    drillsTo: 'the answer lists the data it used',
    scopes: ['portfolio'],
    period: false,
    fields: [{ key: 'show_last', kind: 'number', min: 1, max: 10 }],
  }),
  note: def(NoteWidget, {
    chart: false,
    drillsTo: 'none',
    scopes: ['portfolio'],
    period: false,
    fields: [{ key: 'text', kind: 'longtext' }],
  }),
}

export const REGISTRY: Record<string, WidgetDef> = Object.fromEntries(
  Object.entries(DEFS).map(([type, d]) => [type, { type, ...d }]),
)

/** The widget types a dashboard can hold, in the library's order. */
export const WIDGET_TYPES = Object.keys(REGISTRY)

export function widgetDef(type: string): WidgetDef | undefined {
  return REGISTRY[type]
}
