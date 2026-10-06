import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AccountsTab } from '../components/AccountsTab'
import { SleevesTab } from '../components/SleevesTab'
import { SectionForm } from '../components/SectionForm'
import { AgentTab } from '../agent/AgentTab'
import { MacroTab } from '../notify/MacroTab'
import { NewsTab } from '../news/NewsTab'
import { NotificationsTab } from '../notify/NotificationsTab'
import { SecurityTab } from '../security/SecurityTab'
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
  'macro',
  'news',
  'security',
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
        className={
          ['accounts', 'sleeves', 'notifications', 'macro', 'news', 'agent', 'security'].includes(
            section,
          )
            ? 'max-w-4xl'
            : 'max-w-xl'
        }
      >
        {section === 'accounts' ? (
          <AccountsTab />
        ) : section === 'sleeves' ? (
          <SleevesTab />
        ) : section === 'notifications' ? (
          <NotificationsTab />
        ) : section === 'macro' ? (
          <MacroTab />
        ) : section === 'news' ? (
          <NewsTab />
        ) : section === 'agent' ? (
          <AgentTab />
        ) : section === 'security' ? (
          <SecurityTab />
        ) : (
          <SectionForm key={section} section={section} />
        )}
      </div>
    </div>
  )
}
