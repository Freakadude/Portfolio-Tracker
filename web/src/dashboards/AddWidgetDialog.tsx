import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Dialog } from '../components/display'
import { Input } from '../components/ui'
import { useLibrary, type Config } from './api'
import { KPI_METRICS } from './registry'

/** Lower case, with hyphens and brackets as spaces, so "time weighted" finds "(time-weighted)". */
function plain(text: string): string {
  return text.toLowerCase().replace(/[-()]/g, ' ')
}

/** Every word typed must appear somewhere in the texts. */
function matches(query: string, ...texts: string[]): boolean {
  const hay = plain(texts.join(' '))
  return plain(query)
    .split(/\s+/)
    .filter(Boolean)
    .every((word) => hay.includes(word))
}

const ITEM =
  'w-full rounded-lg border border-border p-3 text-left hover:bg-border/30 focus-visible:outline-2'

/** The widget types to pick from, with a search over their names and descriptions. Figures such
 * as the time-weighted return are settings of the Key figure widget, so a search also lists
 * those and adds a Key figure already set to the one chosen. */
export function AddWidgetDialog({
  onAdd,
  onClose,
}: {
  onAdd: (type: string, config?: Config) => void
  onClose: () => void
}) {
  const { t } = useTranslation()
  const library = useLibrary()
  const [query, setQuery] = useState('')
  const asked = query.trim()
  const widgets = (library.data ?? []).filter(
    (w) => !asked || matches(asked, t(`widgets.${w.type}`), t(`widgetHelp.${w.type}`)),
  )
  const hasKeyFigure = (library.data ?? []).some((w) => w.type === 'kpi')
  const figures =
    asked && hasKeyFigure
      ? KPI_METRICS.filter((m) => matches(asked, t(`widgets.metrics.${m}`), m))
      : []

  return (
    <Dialog open onClose={onClose} title={t('dashboard.addWidget')} wide>
      <div className="mb-3 space-y-1">
        <Input
          type="search"
          autoFocus
          aria-label={t('dashboard.searchWidgets')}
          placeholder={t('dashboard.searchPlaceholder')}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <p className="text-sm text-muted">{t('dashboard.searchHint')}</p>
      </div>
      <ul className="grid gap-2 sm:grid-cols-2">
        {figures.map((metric) => (
          <li key={`figure-${metric}`}>
            <button type="button" onClick={() => onAdd('kpi', { metric })} className={ITEM}>
              <span className="block font-medium">{t(`widgets.metrics.${metric}`)}</span>
              <span className="block text-sm text-muted">{t('dashboard.figureOf')}</span>
            </button>
          </li>
        ))}
        {widgets.map((w) => (
          <li key={w.type}>
            <button type="button" onClick={() => onAdd(w.type)} className={ITEM}>
              <span className="block font-medium">{t(`widgets.${w.type}`)}</span>
              <span className="block text-sm text-muted">{t(`widgetHelp.${w.type}`)}</span>
            </button>
          </li>
        ))}
      </ul>
      {asked && widgets.length === 0 && figures.length === 0 && (
        <p role="status" className="text-sm text-muted">
          {t('dashboard.noMatch', { query: asked })}
        </p>
      )}
    </Dialog>
  )
}
