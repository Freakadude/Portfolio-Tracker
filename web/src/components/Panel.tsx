import { ChevronDown, ChevronRight } from 'lucide-react'
import { useId, useState, type ReactNode } from 'react'
import { cn } from '../lib/cn'

const KEY = 'folio.panel.'

/** The owner's own choice for a section: true closed, false open, null never chosen. */
function chosen(id: string): boolean | null {
  try {
    const value = window.localStorage.getItem(KEY + id)
    return value === null ? null : value === '1'
  } catch {
    return null
  }
}

function choose(id: string, collapsed: boolean) {
  try {
    window.localStorage.setItem(KEY + id, collapsed ? '1' : '0')
  } catch {
    // private windows and blocked storage: the section just starts as it would have
  }
}

/** A page section with a header that stands out and opens and closes it (Insights). The header
 * carries the title, a count and a one-line status that stays readable when the section is
 * closed; `actions` sit in the header but do not toggle it. Until the owner has opened or closed
 * the section themself, it starts closed when `autoCollapse` is set (nothing waiting, or only
 * reference material); after that their choice is remembered in this browser. `forceOpen` keeps
 * it open, for a link that points into it. */
export function Panel({
  id,
  title,
  count,
  status,
  actions,
  autoCollapse = false,
  forceOpen = false,
  children,
}: {
  id: string
  title: string
  count?: number | string
  status?: string
  actions?: ReactNode
  autoCollapse?: boolean
  forceOpen?: boolean
  children: ReactNode
}) {
  const body = useId()
  const [choice, setChoice] = useState<boolean | null>(() => chosen(id))
  const collapsed = forceOpen ? false : (choice ?? autoCollapse)
  const Chevron = collapsed ? ChevronRight : ChevronDown
  return (
    <section
      aria-label={title}
      className="overflow-hidden rounded-xl border border-border bg-card shadow-sm"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-l-4 border-primary bg-gradient-to-r from-primary/15 via-primary/5 to-transparent px-4 py-3">
        <h2 className="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-1 text-xl font-semibold">
          <button
            type="button"
            aria-expanded={!collapsed}
            aria-controls={body}
            onClick={() => {
              if (forceOpen) return
              choose(id, !collapsed)
              setChoice(!collapsed)
            }}
            className="flex min-h-10 items-center gap-2 rounded-md pr-2 text-left hover:bg-primary/10"
          >
            <Chevron aria-hidden="true" className="size-6 shrink-0 text-primary" />
            {title}
          </button>
          {count !== undefined && count !== 0 && count !== '' && (
            <span className="rounded-full bg-primary px-2.5 py-0.5 text-sm font-medium text-primary-foreground">
              {count}
            </span>
          )}
          {status && <span className="text-sm font-normal text-muted">{status}</span>}
        </h2>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
      <div id={body} hidden={collapsed} className={cn('space-y-3 p-4')}>
        {children}
      </div>
    </section>
  )
}
