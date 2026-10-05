import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AccountsTab } from '../components/AccountsTab'
import { SleevesTab } from '../components/SleevesTab'
import { SectionForm } from '../components/SectionForm'
import { cn } from '../lib/cn'

const SECTIONS = [
  'general',
  'accounts',
  'sleeves',
  'providers',
  'agent',
  'schedules',
  'notifications',
  'appearance',
  'language',
  'retention',
  'analytics',
] as const

export function Settings() {
  const { t } = useTranslation()
  const [section, setSection] = useState<(typeof SECTIONS)[number]>('general')
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">{t('settings.title')}</h1>
      <div role="tablist" aria-label={t('settings.title')} className="flex flex-wrap gap-1">
        {SECTIONS.map((s) => (
          <button
            key={s}
            role="tab"
            id={`tab-${s}`}
            aria-selected={section === s}
            aria-controls="settings-panel"
            onClick={() => setSection(s)}
            className={cn(
              'rounded-md px-3 py-2 text-sm',
              section === s ? 'bg-primary text-primary-foreground' : 'hover:bg-border/40',
            )}
          >
            {t(`settings.sections.${s}`)}
          </button>
        ))}
      </div>
      <div
        role="tabpanel"
        id="settings-panel"
        aria-labelledby={`tab-${section}`}
        className={section === 'accounts' || section === 'sleeves' ? 'max-w-4xl' : 'max-w-xl'}
      >
        {section === 'accounts' ? (
          <AccountsTab />
        ) : section === 'sleeves' ? (
          <SleevesTab />
        ) : (
          <SectionForm key={section} section={section} />
        )}
      </div>
    </div>
  )
}
