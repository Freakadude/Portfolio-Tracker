import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { cn } from '../lib/cn'
import { Interview } from './Interview'
import { NotesPanel } from './NotesPanel'
import { PasteMode } from './PasteMode'

type Tab = 'interview' | 'paste' | 'notes'
const TABS: Tab[] = ['interview', 'paste', 'notes']

/** The strategy helper (ADR 0048): help with setting up or revising a strategy, and what it
 * knows about you. */
export function StrategyHelper() {
  const { t } = useTranslation()
  const [tab, setTab] = useState<Tab>('interview')
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-semibold">{t('assistant.title')}</h1>
        <Link to="/strategies" className="text-sm hover:underline">
          {t('assistant.back')}
        </Link>
      </div>
      <p className="text-sm text-muted">{t('assistant.intro')}</p>
      <div role="tablist" aria-label={t('assistant.title')} className="flex flex-wrap gap-1">
        {TABS.map((x) => (
          <button
            key={x}
            type="button"
            role="tab"
            aria-selected={tab === x}
            onClick={() => setTab(x)}
            className={cn(
              'rounded-md px-3 py-1.5 text-sm',
              tab === x ? 'bg-primary text-primary-foreground' : 'hover:bg-border/40',
            )}
          >
            {t(`assistant.tabs.${x}`)}
          </button>
        ))}
      </div>
      <div role="tabpanel">
        {tab === 'interview' && <Interview />}
        {tab === 'paste' && <PasteMode />}
        {tab === 'notes' && <NotesPanel />}
      </div>
    </div>
  )
}
