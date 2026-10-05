import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { useUnread } from '../notify/api'

/** The inbox bell with its unread count, refreshed live by the `notification` event (FR-NT-01). */
export function Bell() {
  const { t } = useTranslation()
  const unread = useUnread().data?.unread ?? 0
  return (
    <Link
      to="/insights"
      className="relative inline-flex min-h-10 items-center gap-1 rounded-md px-2 text-sm hover:bg-border/40"
      aria-label={t('bell.label', { count: unread })}
    >
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        className="h-5 w-5"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
      >
        <path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
        <path d="M13.7 21a2 2 0 0 1-3.4 0" />
      </svg>
      {unread > 0 && (
        <span className="min-w-5 rounded-full bg-primary px-1.5 text-center text-xs font-semibold text-primary-foreground">
          {unread > 99 ? '99+' : unread}
        </span>
      )}
    </Link>
  )
}
