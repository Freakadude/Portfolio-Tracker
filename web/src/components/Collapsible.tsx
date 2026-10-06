import { ChevronDown, ChevronRight, Info } from 'lucide-react'
import { useId, useState, type ReactNode } from 'react'

/** A short explanation that appears when the pointer rests on, or keyboard focus reaches, the
 * small "i" beside a heading. */
export function InfoTip({ text }: { text: string }) {
  const id = useId()
  return (
    <span className="group relative inline-flex">
      <button
        type="button"
        aria-label={text}
        aria-describedby={id}
        className="inline-flex size-6 items-center justify-center rounded-full text-muted hover:text-foreground focus-visible:text-foreground"
      >
        <Info aria-hidden="true" className="size-4" />
      </button>
      <span
        role="tooltip"
        id={id}
        className="pointer-events-none invisible absolute left-0 top-full z-30 mt-1 w-72 max-w-[80vw] rounded-md border border-border bg-card p-2 text-xs font-normal text-foreground opacity-0 shadow transition-opacity group-focus-within:visible group-focus-within:opacity-100 group-hover:visible group-hover:opacity-100"
      >
        {text}
      </span>
    </span>
  )
}

const KEY = 'folio.collapsed.'

function remembered(id: string): boolean {
  try {
    return window.localStorage.getItem(KEY + id) === '1'
  } catch {
    return false
  }
}

function remember(id: string, collapsed: boolean) {
  try {
    if (collapsed) window.localStorage.setItem(KEY + id, '1')
    else window.localStorage.removeItem(KEY + id)
  } catch {
    // private windows and blocked storage: the section simply opens again next time
  }
}

/** A section of a page whose heading opens and closes it. The choice is remembered in this
 * browser. `tip` is the explanation shown on hover beside the heading. */
export function Collapsible({
  id,
  title,
  tip,
  children,
}: {
  id: string
  title: string
  tip?: string
  children: ReactNode
}) {
  const body = useId()
  const [collapsed, setCollapsed] = useState(() => remembered(id))
  const Chevron = collapsed ? ChevronRight : ChevronDown
  return (
    <section aria-label={title} className="space-y-2">
      <div className="flex items-center gap-1">
        <h2 className="text-lg font-medium">
          <button
            type="button"
            aria-expanded={!collapsed}
            aria-controls={body}
            onClick={() => {
              remember(id, !collapsed)
              setCollapsed(!collapsed)
            }}
            className="flex min-h-9 items-center gap-1 rounded-md pr-2 hover:bg-border/40"
          >
            <Chevron aria-hidden="true" className="size-5" />
            {title}
          </button>
        </h2>
        {tip && <InfoTip text={tip} />}
      </div>
      <div id={body} hidden={collapsed}>
        {children}
      </div>
    </section>
  )
}
