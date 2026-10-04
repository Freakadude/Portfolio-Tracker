import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { cn } from '../lib/cn'
import { ARROWS, SIGNS, direction, toNumber } from '../lib/format'
import { useFormat } from '../lib/useFormat'
import { Button } from './ui'

/** A gain or loss: sign, arrow and colour together, so meaning never depends on colour alone. */
export function Delta({ value, kind = 'eur' }: { value?: string | null; kind?: 'eur' | 'pct' }) {
  const { t } = useTranslation()
  const { eur, pct } = useFormat()
  const n = toNumber(value)
  if (n === null) return <span className="text-muted">–</span>
  const dir = direction(value, kind === 'pct' ? 0.00005 : 0.005)
  const shown = kind === 'eur' ? eur(Math.abs(n)) : pct(Math.abs(n))
  return (
    <span
      className={cn(
        'whitespace-nowrap tabular-nums',
        dir === 'up' && 'text-gain',
        dir === 'down' && 'text-danger',
        dir === 'flat' && 'text-muted',
      )}
    >
      {SIGNS[dir]}
      {shown} <span aria-hidden="true">{ARROWS[dir]}</span>
      <span className="sr-only">{t(`delta.${dir}`)}</span>
    </span>
  )
}

/** Euro amount and its percentage, both as gains or losses. */
export function Gain({ eur, ratio }: { eur?: string | null; ratio?: string | null }) {
  return (
    <span className="inline-flex flex-col items-end leading-tight">
      <Delta value={eur} />
      <span className="text-xs">
        <Delta value={ratio} kind="pct" />
      </span>
    </span>
  )
}

export function Badge({
  tone = 'neutral',
  children,
  title,
}: {
  tone?: 'neutral' | 'warn' | 'good' | 'bad'
  children: ReactNode
  title?: string
}) {
  return (
    <span
      title={title}
      className={cn(
        'inline-block rounded border px-1.5 py-0.5 text-xs font-medium',
        tone === 'neutral' && 'border-border text-muted',
        tone === 'warn' &&
          'border-amber-600 text-amber-700 dark:border-amber-400 dark:text-amber-300',
        tone === 'good' && 'border-gain text-gain',
        tone === 'bad' && 'border-danger text-danger',
      )}
    >
      {children}
    </span>
  )
}

/** Every page says what to do next when it has nothing to show. */
export function EmptyState({
  title,
  body,
  action,
}: {
  title: string
  body: string
  action?: ReactNode
}) {
  return (
    <div className="max-w-xl space-y-2 rounded-lg border border-dashed border-border p-6">
      <h2 className="text-lg font-medium">{title}</h2>
      <p className="text-muted">{body}</p>
      {action && <div className="pt-2">{action}</div>}
    </div>
  )
}

/** A modal built on the native dialog element, which handles focus and Escape. */
export function Dialog({
  open,
  onClose,
  title,
  children,
  wide = false,
}: {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  wide?: boolean
}) {
  const { t } = useTranslation()
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open && !dialog.open) {
      if (typeof dialog.showModal === 'function') dialog.showModal()
      else dialog.setAttribute('open', '')
    }
    if (!open && dialog.open) {
      if (typeof dialog.close === 'function') dialog.close()
      else dialog.removeAttribute('open')
    }
  }, [open])
  if (!open) return null
  return (
    <dialog
      ref={ref}
      aria-label={title}
      onCancel={(e) => {
        e.preventDefault()
        onClose()
      }}
      className={cn(
        'm-auto max-h-[90vh] w-[calc(100vw-2rem)] overflow-y-auto rounded-lg border border-border bg-card p-0 text-foreground backdrop:bg-black/50',
        wide ? 'max-w-3xl' : 'max-w-lg',
      )}
    >
      <div className="flex items-center justify-between border-b border-border px-5 py-3">
        <h2 className="text-lg font-semibold">{title}</h2>
        <Button variant="ghost" onClick={onClose} aria-label={t('app.close')}>
          ✕
        </Button>
      </div>
      <div className="p-5">{children}</div>
    </dialog>
  )
}

export type SortState<K extends string> = { key: K; dir: 'asc' | 'desc' }

/** Sorting for a table: click a header to sort, click again to reverse. */
export function useSort<T, K extends string>(
  rows: T[],
  accessors: Record<K, (row: T) => string | number | null>,
  initial: SortState<K>,
) {
  const [sort, setSort] = useState<SortState<K>>(initial)
  const sorted = useMemo(() => {
    const get = accessors[sort.key]
    const factor = sort.dir === 'asc' ? 1 : -1
    return [...rows].sort((a, b) => {
      const x = get(a)
      const y = get(b)
      if (x === y) return 0
      if (x === null) return 1 // rows without a value go last either way
      if (y === null) return -1
      return (x < y ? -1 : 1) * factor
    })
  }, [rows, accessors, sort])
  const toggle = (key: K) =>
    setSort((s) =>
      s.key === key ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: 'asc' },
    )
  return { sorted, sort, toggle }
}

export function SortHeader<K extends string>({
  label,
  sortKey,
  sort,
  onSort,
  align = 'right',
}: {
  label: string
  sortKey: K
  sort: SortState<K>
  onSort: (key: K) => void
  align?: 'left' | 'right'
}) {
  const active = sort.key === sortKey
  return (
    <th
      scope="col"
      aria-sort={active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}
      className={cn('px-3 py-2 font-medium', align === 'right' ? 'text-right' : 'text-left')}
    >
      <button type="button" onClick={() => onSort(sortKey)} className="font-medium hover:underline">
        {label}
        <span aria-hidden="true" className="ml-1 text-xs">
          {active ? (sort.dir === 'asc' ? '▲' : '▼') : ''}
        </span>
      </button>
    </th>
  )
}

/** "as of" time shown on hover wherever a figure depends on a price. */
export function AsOf({
  date,
  source,
  children,
}: {
  date?: string | null
  source?: string | null
  children: ReactNode
}) {
  const { t } = useTranslation()
  const title = date ? t('asof.title', { date, source: source ?? '' }) : undefined
  return <span title={title}>{children}</span>
}
