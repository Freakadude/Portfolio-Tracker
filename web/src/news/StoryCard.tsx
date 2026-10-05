import { useTranslation } from 'react-i18next'
import { errorMessage } from '../api/client'
import { Badge } from '../components/display'
import { Alert, Button } from '../components/ui'
import { useNewsFeedback, type NewsCluster } from './api'

const TONE = { negative: 'bad', positive: 'good', mixed: 'warn', unclear: 'neutral' } as const

/** One story: where it was reported, what it touches and why (direct, through an ETF with the
 * weight shown, or via a theme), the model's assessment, and the feedback buttons (FR-NW-07,
 * FR-NW-08). Everything is plain text: news copy is never rendered as markup. */
export function StoryCard({ story }: { story: NewsCluster }) {
  const { t } = useTranslation()
  const feedback = useNewsFeedback()
  const a = story.assessment
  const first = story.items[0]
  const mark = (verdict: 'useful' | 'not_relevant', linkId?: number) =>
    feedback.mutate({ id: story.id, verdict, linkId })
  return (
    <article
      aria-labelledby={`story-${story.id}`}
      className="space-y-2 rounded-md border border-border p-4"
    >
      <header className="space-y-1">
        <h2 id={`story-${story.id}`} className="font-medium">
          {story.title}
        </h2>
        <p className="flex flex-wrap items-center gap-2 text-xs text-muted">
          <time dateTime={story.last_seen}>{new Date(story.last_seen).toLocaleString()}</time>
          {a && (
            <>
              <Badge
                tone={a.impact_score >= 70 ? 'bad' : a.impact_score >= 40 ? 'warn' : 'neutral'}
              >
                {t('news.impact', { score: a.impact_score })}
              </Badge>
              <Badge tone={TONE[a.direction as keyof typeof TONE] ?? 'neutral'}>
                {t(`news.direction.${a.direction}`)}
              </Badge>
              <span>{t(`news.horizon.${a.horizon}`)}</span>
              <span>{t('news.confidence', { level: t(`news.level.${a.confidence}`) })}</span>
            </>
          )}
        </p>
      </header>
      {a && <p className="text-sm">{a.rationale}</p>}
      {a && a.affected.length > 0 && (
        <p className="text-sm text-muted">{t('news.affects', { names: a.affected.join(', ') })}</p>
      )}
      {story.links.length > 0 && (
        <ul aria-label={t('news.links')} className="space-y-0.5 text-sm">
          {story.links.map((k) => (
            <li key={k.id} className="flex flex-wrap items-center gap-2">
              <span>
                {k.label}
                {' · '}
                {t(`news.linkType.${k.link_type}`)}
                {k.weight_pct !== null &&
                  ` · ${t('news.weightInFund', { pct: Number(k.weight_pct).toFixed(1) })}`}
              </span>
              {k.matched_by.startsWith('alias:') && (
                <button
                  type="button"
                  className="text-xs underline"
                  onClick={() => mark('not_relevant', k.id)}
                  aria-label={t('news.wrongLinkFor', { name: k.label })}
                >
                  {t('news.wrongLink')}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      <ul aria-label={t('news.reportedBy')} className="space-y-0.5 text-sm">
        {story.items.map((i) => (
          <li key={i.id}>
            <span className="text-muted">{i.source}: </span>
            <a href={i.url} target="_blank" rel="noopener noreferrer" className="underline">
              {i.title}
            </a>
          </li>
        ))}
      </ul>
      {first && story.items.length > 1 && (
        <p className="text-xs text-muted">{t('news.sources', { count: story.items.length })}</p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="secondary"
          onClick={() => mark('useful')}
          disabled={feedback.isPending}
          aria-label={`${t('news.useful')}: ${story.title}`}
        >
          {t('news.useful')}
        </Button>
        <Button
          variant="secondary"
          onClick={() => mark('not_relevant')}
          disabled={feedback.isPending}
          aria-label={`${t('news.notRelevant')}: ${story.title}`}
        >
          {t('news.notRelevant')}
        </Button>
        {feedback.isSuccess && (
          <span role="status" className="text-sm">
            {feedback.data.changes.length === 0
              ? t('news.thanks')
              : feedback.data.changes
                  .map((c) => t(`news.change.${c.kind}`, { name: c.name, old: c.old, new: c.new }))
                  .join(' ')}
          </span>
        )}
      </div>
      {feedback.isError && <Alert>{errorMessage(feedback.error)}</Alert>}
    </article>
  )
}
