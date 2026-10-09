import { useMemo, useRef, useState, type RefObject } from 'react'
import { useTranslation } from 'react-i18next'
import { cn } from '../lib/cn'
import { Responsive, useContainerWidth } from 'react-grid-layout'
import 'react-grid-layout/css/styles.css'
import 'react-resizable/css/styles.css'
import { Button } from '../components/ui'
import {
  useWidgetData,
  type Box,
  type Config,
  type Dashboard,
  type DashboardWidget,
  type Filters,
  type Layouts,
  type WidgetResult,
} from './api'
import { widgetDef } from './registry'

// widths of the dashboard area, not of the window: a laptop is desktop, a phone is one column
export const BREAKPOINTS = { lg: 900, md: 560, sm: 0 } as const
export const COLS = { lg: 12, md: 8, sm: 1 } as const
export type Breakpoint = keyof typeof COLS

export function widgetTitle(
  t: (key: string) => string,
  widget: Pick<DashboardWidget, 'type' | 'config'>,
): string {
  const custom = (widget.config as Config).title
  if (typeof custom === 'string' && custom.trim()) return custom
  // a figure tile is named by what it shows
  const metric = (widget.config as Config).metric
  if (widget.type === 'kpi' && typeof metric === 'string') return t(`widgets.metrics.${metric}`)
  return t(`widgets.${widget.type}`)
}

/** The tints a note can have: the app's own colours mixed into the card colour, so the text
 * keeps its contrast in the light and the dark theme. */
const NOTE_TINT: Record<string, string> = {
  blue: 'var(--primary)',
  green: 'var(--gain)',
  amber: '#d97706',
  red: 'var(--danger)',
  purple: '#7c3aed',
  grey: 'var(--muted)',
}
const TITLE_SIZE: Record<string, string> = {
  small: 'truncate text-sm font-medium',
  medium: 'text-lg font-semibold leading-snug',
  large: 'text-2xl font-semibold leading-tight',
  xlarge: 'text-4xl font-bold leading-tight',
}

/** How a note looks: the size of its title, a tint behind it, and whether the title stands alone. */
export function noteLook(widget: Pick<DashboardWidget, 'type' | 'config'>) {
  const config = widget.config as Config
  if (widget.type !== 'note') {
    return { titleClass: TITLE_SIZE.small, style: undefined, titleOnly: false }
  }
  const tint = NOTE_TINT[String(config.background)]
  return {
    titleClass: TITLE_SIZE[String(config.title_size)] ?? TITLE_SIZE.small,
    style: tint ? { background: `color-mix(in oklab, ${tint} 16%, var(--card))` } : undefined,
    titleOnly: config.title_only === true,
  }
}

/** One widget's frame: its title, and either its picture, its error or an empty state. */
export function WidgetBody({
  widget,
  result,
  filters,
  loading,
}: {
  widget: Pick<DashboardWidget, 'id' | 'type' | 'config'>
  result: WidgetResult | undefined
  filters: Filters
  loading: boolean
}) {
  const { t } = useTranslation()
  const def = widgetDef(widget.type)
  if (!def)
    return (
      <p className="text-sm text-danger">{t('dashboard.unknownWidget', { type: widget.type })}</p>
    )
  if (!result) return <p className="text-sm text-muted">{loading ? t('app.loading') : ''}</p>
  if (result.error)
    return (
      <p role="alert" className="text-sm text-danger">
        {result.error}
      </p>
    )
  const data = (result.data ?? {}) as Record<string, unknown>
  // "empty" answers are drawn by the widget itself, so each can say what to do next
  return <def.Component data={data} config={widget.config as Config} filters={filters} />
}

interface Props {
  dashboard: Dashboard
  /** The period and account the widgets follow. */
  filters: Filters
  editing: boolean
  onLayoutChange: (layouts: Layouts) => void
  onConfigure: (widget: DashboardWidget) => void
  onRemove: (widget: DashboardWidget) => void
  onBreakpoint?: (bp: Breakpoint) => void
}

function sameLayouts(a: Layouts, b: Layouts): boolean {
  return JSON.stringify(a) === JSON.stringify(b)
}

export function DashboardView({
  dashboard,
  filters,
  editing,
  onLayoutChange,
  onConfigure,
  onRemove,
  onBreakpoint,
}: Props) {
  const { t } = useTranslation()
  const { width, containerRef, mounted } = useContainerWidth()
  const widgets = dashboard.widgets
  const requests = useMemo(
    () => widgets.map((w) => ({ key: String(w.id), type: w.type, config: w.config as Config })),
    [widgets],
  )
  const query = useWidgetData(requests, filters)
  const saved = useRef(dashboard.layouts as Layouts)
  saved.current = dashboard.layouts as Layouts
  const [breakpoint, setBreakpoint] = useState<Breakpoint>('lg')
  /** A drag or a resize has ended: save the layout the grid arrived at, if it changed. The
   * layout handed over is the current breakpoint's, the others stay as they were saved. */
  const flush = (layout: readonly { i: string; x: number; y: number; w: number; h: number }[]) => {
    if (!editing) return
    const here = layout.map((b) => ({ i: b.i, x: b.x, y: b.y, w: b.w, h: b.h }) as Box)
    const next: Layouts = { ...saved.current, [breakpoint]: here }
    if (!sameLayouts(next, saved.current)) onLayoutChange(next)
  }

  const layouts = dashboard.layouts as Layouts
  return (
    <div
      ref={containerRef as RefObject<HTMLDivElement>}
      className={query.isPlaceholderData ? 'opacity-70 transition-opacity' : undefined}
    >
      {mounted && (
        <Responsive
          width={width}
          layouts={layouts}
          breakpoints={BREAKPOINTS}
          cols={COLS}
          rowHeight={56}
          margin={[12, 12]}
          dragConfig={{
            enabled: editing,
            handle: '.widget-handle',
            cancel: '.widget-cancel',
            bounded: false,
            threshold: 3,
          }}
          resizeConfig={{ enabled: editing, handles: ['se'] }}
          onBreakpointChange={(bp) => {
            setBreakpoint(bp as Breakpoint)
            onBreakpoint?.(bp as Breakpoint)
          }}
          onDragStop={flush}
          onResizeStop={flush}
        >
          {widgets.map((w) => {
            const look = noteLook(w)
            return (
              <section
                key={String(w.id)}
                aria-label={widgetTitle(t, w)}
                style={look.style}
                className="flex min-w-0 flex-col overflow-hidden rounded-lg border border-border bg-card"
              >
                <header
                  className={cn(
                    'flex items-center justify-between gap-2 px-3 py-1.5',
                    look.titleOnly ? 'min-h-0 flex-1' : 'border-b border-border',
                  )}
                >
                  <h2 className={look.titleClass}>{widgetTitle(t, w)}</h2>
                  {editing && (
                    <div className="flex shrink-0 items-center gap-0.5">
                      <button
                        type="button"
                        className="widget-handle min-h-8 cursor-grab rounded px-2 hover:bg-border/40"
                        aria-label={t('dashboard.move', { name: widgetTitle(t, w) })}
                        title={t('dashboard.moveHint')}
                      >
                        ⠿
                      </button>
                      <Button
                        variant="ghost"
                        className="widget-cancel min-h-8 px-2"
                        onClick={() => onConfigure(w)}
                        aria-label={t('dashboard.configure', { name: widgetTitle(t, w) })}
                      >
                        ✎
                      </Button>
                      <Button
                        variant="ghost"
                        className="widget-cancel min-h-8 px-2"
                        onClick={() => onRemove(w)}
                        aria-label={t('dashboard.remove', { name: widgetTitle(t, w) })}
                      >
                        ✕
                      </Button>
                    </div>
                  )}
                </header>
                {!look.titleOnly && (
                  <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-auto p-3">
                    <WidgetBody
                      widget={w}
                      result={query.data?.[String(w.id)]}
                      filters={filters}
                      loading={query.isLoading}
                    />
                  </div>
                )}
              </section>
            )
          })}
        </Responsive>
      )}
      <span className="sr-only" data-breakpoint={breakpoint} />
    </div>
  )
}
