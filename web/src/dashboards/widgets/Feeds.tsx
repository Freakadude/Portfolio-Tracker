import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { AskPanel } from '../../agent/Ask'
import { Badge } from '../../components/display'
import type { WidgetProps } from '../types'

const TONE = {
  critical: 'bad',
  high: 'bad',
  medium: 'warn',
  low: 'neutral',
  info: 'neutral',
} as const

export interface NewsFeedData {
  empty?: true
  reason?: string
  stories?: {
    id: number
    title: string
    last_seen: string
    impact: number | null
    direction: string | null
    links: string[]
  }[]
}

export interface SignalsData {
  empty?: true
  reason?: string
  items?: {
    kind: 'recommendation' | 'signal'
    id: number
    title: string
    severity: string
    time: string
    departs: boolean
  }[]
}

/** The latest stories linked to what you hold; a click opens the story on the News page. */
export function NewsFeedWidget({ data }: WidgetProps<NewsFeedData>) {
  const { t } = useTranslation()
  if (data.empty) return <p className="text-sm text-muted">{data.reason}</p>
  return (
    <ul aria-label={t('widgets.news_feed')} className="space-y-2 text-sm">
      {(data.stories ?? []).map((s) => (
        <li key={s.id}>
          <Link to={`/news?cluster=${s.id}`} className="font-medium hover:underline">
            {s.title}
          </Link>
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
            <time dateTime={s.last_seen}>{new Date(s.last_seen).toLocaleDateString()}</time>
            {s.impact !== null && <Badge>{t('news.impact', { score: s.impact })}</Badge>}
            {s.direction && <span>{t(`news.direction.${s.direction}`)}</span>}
            {s.links.length > 0 && <span>{s.links.join(', ')}</span>}
          </div>
        </li>
      ))}
    </ul>
  )
}

/** What waits for you: open recommendations first, then the strategy's recent signals. */
export function SignalsWidget({ data }: WidgetProps<SignalsData>) {
  const { t } = useTranslation()
  if (data.empty) return <p className="text-sm text-muted">{data.reason}</p>
  return (
    <ul aria-label={t('widgets.signals')} className="space-y-2 text-sm">
      {(data.items ?? []).map((i) => (
        <li key={`${i.kind}-${i.id}`}>
          <Link
            to={i.kind === 'recommendation' ? `/insights?recommendation=${i.id}` : '/strategies'}
            className="font-medium hover:underline"
          >
            {i.title}
          </Link>
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
            <Badge tone={TONE[i.severity as keyof typeof TONE] ?? 'neutral'}>
              {t(`recs.severity.${i.severity}`)}
            </Badge>
            <Badge>{i.kind === 'recommendation' ? t('recs.ai') : t('signalsWidget.signal')}</Badge>
            {i.departs && <Badge tone="warn">{t('recs.departs')}</Badge>}
            <time dateTime={i.time}>{new Date(i.time).toLocaleDateString()}</time>
          </div>
        </li>
      ))}
    </ul>
  )
}

export interface AskData {
  empty?: boolean
  reason?: string | null
  show_last?: number
}

/** The question box on a dashboard (FR-DB-09): the agent answers from your data and the answer
 * lists the rows it used. */
export function AskWidget({ data }: WidgetProps<AskData>) {
  if (data.empty) return <p className="text-sm text-muted">{data.reason}</p>
  return <AskPanel showLast={data.show_last ?? 3} />
}
