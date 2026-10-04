import { useTranslation } from 'react-i18next'
import { Card } from '../components/ui'

/** Every page starts with an empty state that says what to do next. */
export function Placeholder({ page }: { page: string }) {
  const { t } = useTranslation()
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">{t(`nav.${page}`)}</h1>
      <Card className="max-w-xl space-y-2">
        <h2 className="text-lg font-medium">{t(`empty.${page}.title`)}</h2>
        <p className="text-muted">{t(`empty.${page}.body`)}</p>
        {page !== 'home' && <p className="text-sm text-muted">{t('empty.comingLater')}</p>}
      </Card>
    </div>
  )
}
