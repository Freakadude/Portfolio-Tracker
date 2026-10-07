import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { NotesPanel } from './NotesPanel'

/** The strategy helper (ADR 0048): what it knows about you, and the ways to get help with a
 * strategy. */
export function StrategyHelper() {
  const { t } = useTranslation()
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-semibold">{t('assistant.title')}</h1>
        <Link to="/strategies" className="text-sm hover:underline">
          {t('assistant.back')}
        </Link>
      </div>
      <p className="text-sm text-muted">{t('assistant.intro')}</p>
      <NotesPanel />
    </div>
  )
}
