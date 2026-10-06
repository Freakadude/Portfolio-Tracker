import { Banknote, Briefcase, Building2, Gem, Landmark, Layers, Shapes } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { cn } from '../lib/cn'

/** One look per kind of instrument, so a list or a page tells at a glance what it is about:
 * a colour (never green or red, which mean gain and loss) and an icon. The label is always
 * written too, so colour is never the only signal. */
const STYLES: Record<string, { icon: LucideIcon; badge: string; tile: string }> = {
  ETF: {
    icon: Layers,
    badge:
      'border-sky-600 bg-sky-50 text-sky-800 dark:border-sky-400 dark:bg-sky-950 dark:text-sky-200',
    tile: 'bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-200',
  },
  EQUITY: {
    icon: Building2,
    badge:
      'border-violet-600 bg-violet-50 text-violet-800 dark:border-violet-400 dark:bg-violet-950 dark:text-violet-200',
    tile: 'bg-violet-100 text-violet-800 dark:bg-violet-950 dark:text-violet-200',
  },
  BOND: {
    icon: Landmark,
    badge:
      'border-teal-600 bg-teal-50 text-teal-800 dark:border-teal-400 dark:bg-teal-950 dark:text-teal-200',
    tile: 'bg-teal-100 text-teal-800 dark:bg-teal-950 dark:text-teal-200',
  },
  ETC: {
    icon: Gem,
    badge:
      'border-amber-600 bg-amber-50 text-amber-800 dark:border-amber-400 dark:bg-amber-950 dark:text-amber-200',
    tile: 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200',
  },
  FUND: {
    icon: Briefcase,
    badge:
      'border-rose-600 bg-rose-50 text-rose-800 dark:border-rose-400 dark:bg-rose-950 dark:text-rose-200',
    tile: 'bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-200',
  },
  CASH: {
    icon: Banknote,
    badge:
      'border-slate-500 bg-slate-100 text-slate-800 dark:border-slate-400 dark:bg-slate-800 dark:text-slate-200',
    tile: 'bg-slate-200 text-slate-800 dark:bg-slate-800 dark:text-slate-200',
  },
  OTHER: {
    icon: Shapes,
    badge:
      'border-stone-500 bg-stone-100 text-stone-800 dark:border-stone-400 dark:bg-stone-800 dark:text-stone-200',
    tile: 'bg-stone-200 text-stone-800 dark:bg-stone-800 dark:text-stone-200',
  },
}

const styleOf = (assetClass: string) => STYLES[assetClass] ?? STYLES.OTHER

/** The kind of instrument as a small coloured label with its icon, for lists and tables. */
export function TypeBadge({ assetClass }: { assetClass: string }) {
  const { t } = useTranslation()
  const { icon: Icon, badge } = styleOf(assetClass)
  return (
    <span
      data-asset-class={assetClass}
      className={cn(
        'inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-xs font-medium',
        badge,
      )}
    >
      <Icon aria-hidden="true" className="size-3" />
      {t(`assetClass.${assetClass}`, { defaultValue: assetClass })}
    </span>
  )
}

/** The kind of instrument as a larger icon tile, for the header of an instrument's page. */
export function TypeIcon({ assetClass }: { assetClass: string }) {
  const { t } = useTranslation()
  const { icon: Icon, tile } = styleOf(assetClass)
  return (
    <span
      aria-hidden="true" // the page also writes the kind in words under the name
      title={t(`assetClass.${assetClass}`, { defaultValue: assetClass })}
      data-asset-class={assetClass}
      className={cn('inline-flex size-9 shrink-0 items-center justify-center rounded-lg', tile)}
    >
      <Icon aria-hidden="true" className="size-5" />
    </span>
  )
}
