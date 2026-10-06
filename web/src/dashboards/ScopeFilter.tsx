import { useTranslation } from 'react-i18next'
import { usePositions } from '../api/queries'
import { cn } from '../lib/cn'
import type { Filters } from './api'

const TYPES = ['ETF', 'ETC', 'EQUITY', 'BOND', 'FUND', 'CASH', 'OTHER'] as const

/** The second row of a dashboard's filters: which instrument types, or which holdings, the
 * figures and charts are about. Nothing chosen means everything. Choosing both lets either
 * one count. */
export function ScopeFilter({
  filters,
  onChange,
}: {
  filters: Filters
  onChange: (patch: Pick<Filters, 'types' | 'instruments'>) => void
}) {
  const { t } = useTranslation()
  const held = usePositions({ groupByIsin: true })
  const types = filters.types ?? []
  const chosen = filters.instruments ?? []
  const holdings = (held.data?.positions ?? []).map((p) => ({ id: p.instrument_id, name: p.name }))
  const present = new Set((held.data?.positions ?? []).map((p) => p.asset_class))
  const shown = TYPES.filter((c) => present.has(c) || types.includes(c))
  const toggle = <T,>(list: T[], item: T) =>
    list.includes(item) ? list.filter((x) => x !== item) : [...list, item]
  if (holdings.length === 0 && types.length === 0 && chosen.length === 0) return null

  return (
    <div
      className="flex flex-wrap items-center gap-x-4 gap-y-2"
      role="group"
      aria-label={t('dashboard.scopeFilter.label')}
    >
      <span className="text-sm font-medium">{t('dashboard.scopeFilter.show')}</span>
      <button
        type="button"
        aria-pressed={types.length === 0 && chosen.length === 0}
        onClick={() => onChange({ types: [], instruments: [] })}
        className={cn(
          'min-h-9 rounded-md px-3 text-sm',
          types.length === 0 && chosen.length === 0
            ? 'bg-primary text-primary-foreground'
            : 'border border-border hover:bg-border/40',
        )}
      >
        {t('dashboard.scopeFilter.everything')}
      </button>
      <div role="group" aria-label={t('dashboard.scopeFilter.types')} className="flex gap-1">
        {shown.map((c) => (
          <button
            key={c}
            type="button"
            aria-pressed={types.includes(c)}
            onClick={() => onChange({ types: toggle(types, c), instruments: chosen })}
            className={cn(
              'min-h-9 rounded-md px-3 text-sm',
              types.includes(c)
                ? 'bg-primary text-primary-foreground'
                : 'border border-border hover:bg-border/40',
            )}
          >
            {t(`assetClass.${c}`)}
          </button>
        ))}
      </div>
      {holdings.length > 0 && (
        <details className="relative">
          <summary className="min-h-9 cursor-pointer list-none rounded-md border border-border px-3 py-2 text-sm hover:bg-border/40">
            {chosen.length === 0
              ? t('dashboard.scopeFilter.holdings')
              : t('dashboard.scopeFilter.holdingsChosen', { count: chosen.length })}
          </summary>
          <fieldset className="absolute z-20 mt-1 max-h-72 min-w-56 space-y-1 overflow-auto rounded-md border border-border bg-card p-3 shadow">
            <legend className="sr-only">{t('dashboard.scopeFilter.holdings')}</legend>
            {holdings.map((h) => (
              <label key={h.id} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={chosen.includes(h.id)}
                  onChange={() => onChange({ types, instruments: toggle(chosen, h.id) })}
                />
                {h.name}
              </label>
            ))}
          </fieldset>
        </details>
      )}
    </div>
  )
}
