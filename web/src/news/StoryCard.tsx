import { ArrowLeftRight, CircleHelp, Lightbulb, TrendingDown, TrendingUp } from 'lucide-react'
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../api/client'
import { Alert, Button } from '../components/ui'
import { cn } from '../lib/cn'
import { useFormat } from '../lib/useFormat'
import { useNewsFeedback, type NewsCluster } from './api'

type Link = NewsCluster['links'][number]

/** The stripe down the left of a card and the badge of the potential: how big the effect could
 * become, so the cards that matter stand out from a distance. */
const LEVEL = {
  high: { stripe: 'border-l-danger', badge: 'border-danger bg-danger/10 text-danger' },
  mid: {
    stripe: 'border-l-amber-500',
    badge:
      'border-amber-600 bg-amber-500/10 text-amber-800 dark:border-amber-400 dark:text-amber-300',
  },
  low: { stripe: 'border-l-primary/40', badge: 'border-border bg-border/30 text-muted' },
} as const

const DIRECTION = {
  positive: { Icon: TrendingUp, text: 'text-gain' },
  negative: { Icon: TrendingDown, text: 'text-danger' },
  mixed: { Icon: ArrowLeftRight, text: 'text-amber-700 dark:text-amber-300' },
  unclear: { Icon: CircleHelp, text: 'text-muted' },
} as const

const LABEL = 'text-xs font-semibold uppercase tracking-wide text-muted'

/** "constituent:apple inc" or "alias:asml" as the name it matched on, for a person to read. */
function matchedName(matchedBy: string): string {
  const name = matchedBy.split(':').slice(1).join(':')
  return name.replace(/\b\w/g, (c) => c.toUpperCase())
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section aria-label={title} className="space-y-1.5">
      <h3 className={LABEL}>{title}</h3>
      {children}
    </section>
  )
}

/** One story, in bands the eye can tell apart: the title, what it touches (how directly), what
 * was reported, the impact now, what could happen later and what could be done about it, then
 * the feedback buttons (FR-NW-07, FR-NW-08, ADR 0061). Everything is plain text: news copy is
 * never rendered as markup. */
export function StoryCard({ story }: { story: NewsCluster }) {
  const { t } = useTranslation()
  const { num } = useFormat()
  const feedback = useNewsFeedback()
  const a = story.assessment
  const mark = (verdict: 'useful' | 'not_relevant', linkId?: number) =>
    feedback.mutate({ id: story.id, verdict, linkId })
  const level = a ? (a.outlook_level as keyof typeof LEVEL) : null
  const stripe = level ? (LEVEL[level]?.stripe ?? 'border-l-border') : 'border-l-border'
  const withSummary = story.items.find((i) => i.summary) ?? story.items[0]
  const others = story.items.filter((i) => i !== withSummary)
  const when = new Date(story.last_seen).toLocaleString()

  const chip = (k: Link, group: 'direct' | 'fund' | 'indirect' | 'watch') => {
    const wrong = k.matched_by.startsWith('alias:') && (
      <button
        type="button"
        className="ml-1 rounded px-1 text-xs underline"
        onClick={() => mark('not_relevant', k.id)}
        aria-label={t('news.wrongLinkFor', { name: k.label })}
      >
        {t('news.wrongLink')}
      </button>
    )
    const weight =
      k.portfolio_weight_pct !== null && group === 'direct'
        ? t('news.touches.portfolioShare', { pct: num(k.portfolio_weight_pct, 1) })
        : null
    const base = 'inline-flex flex-wrap items-center gap-x-2 rounded-md px-2.5 py-1 text-sm'
    if (group === 'fund') {
      return (
        <li key={k.id} className={cn(base, 'border-2 border-primary text-foreground')}>
          <span className="font-semibold">{k.label}</span>
          <span>
            {t('news.touches.insideFund', {
              company: matchedName(k.matched_by),
              pct: num(k.weight_pct, 1),
            })}
          </span>
          {wrong}
        </li>
      )
    }
    if (group === 'indirect' || group === 'watch') {
      const how =
        k.link_type === 'macro'
          ? t('news.touches.viaMacro')
          : k.link_type === 'theme'
            ? t('news.touches.viaTheme')
            : null
      return (
        <li key={k.id} className={cn(base, 'border border-dashed border-muted text-foreground')}>
          <span className="font-medium">
            {k.instrument_id === null ? t('news.touches.sleeve', { name: k.label }) : k.label}
          </span>
          {group === 'watch' && <span className="text-muted">{t('news.touches.watchedOnly')}</span>}
          {how && <span className="text-muted">{how}</span>}
          {k.reason && (
            <span className="text-muted">{t('news.touches.reason', { reason: k.reason })}</span>
          )}
          {wrong}
        </li>
      )
    }
    return (
      <li key={k.id} className={cn(base, 'bg-primary text-primary-foreground')}>
        <span className="font-semibold">{k.label}</span>
        {weight && <span className="opacity-90">{weight}</span>}
        {wrong}
      </li>
    )
  }

  // how directly each link reaches the owner decides the group it is shown in
  const held = story.links.filter((k) => k.held && k.instrument_id !== null)
  const groups: { id: 'direct' | 'fund' | 'indirect' | 'watch'; links: Link[] }[] = [
    { id: 'direct', links: held.filter((k) => k.link_type === 'direct') },
    { id: 'fund', links: held.filter((k) => k.link_type === 'look_through') },
    {
      id: 'indirect',
      links: story.links.filter(
        (k) => k.instrument_id === null || k.link_type === 'theme' || k.link_type === 'macro',
      ),
    },
    {
      id: 'watch',
      links: story.links.filter(
        (k) =>
          !k.held &&
          k.instrument_id !== null &&
          (k.link_type === 'direct' || k.link_type === 'look_through'),
      ),
    },
  ]

  return (
    <article
      aria-labelledby={`story-${story.id}`}
      className={cn(
        'overflow-hidden rounded-xl border border-l-[6px] border-border bg-card shadow-sm',
        'transition-shadow focus-within:shadow-md hover:shadow-md',
        stripe,
      )}
    >
      <header className="space-y-1 px-5 pb-3 pt-4">
        <h2 id={`story-${story.id}`} className="text-xl font-semibold leading-snug">
          {story.title}
        </h2>
        <p className="text-sm text-muted">
          <time dateTime={story.last_seen}>{when}</time>
          {story.items.length > 1 && ` · ${t('news.sources', { count: story.items.length })}`}
        </p>
      </header>

      <div className="space-y-2 border-y border-border bg-primary/5 px-5 py-3">
        <h3 className={LABEL}>{t('news.touches.title')}</h3>
        {groups.every((g) => g.links.length === 0) ? (
          <p className="text-sm text-muted">{t('news.touches.none')}</p>
        ) : (
          groups
            .filter((g) => g.links.length > 0)
            .map((g) => (
              <div key={g.id} className="space-y-1">
                <p className="text-sm font-medium">{t(`news.touches.${g.id}`)}</p>
                <ul aria-label={t(`news.touches.${g.id}`)} className="flex flex-wrap gap-2">
                  {g.links.map((k) => chip(k, g.id))}
                </ul>
              </div>
            ))
        )}
      </div>

      <div className="space-y-4 px-5 py-4">
        {withSummary && (
          <Section title={t('news.reported.title')}>
            {withSummary.summary ? (
              <p className="text-base leading-relaxed">{withSummary.summary}</p>
            ) : (
              <p className="text-sm text-muted">{t('news.reported.headlineOnly')}</p>
            )}
            <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
              <a
                href={withSummary.url}
                target="_blank"
                rel="noopener noreferrer"
                className="font-medium underline"
              >
                {withSummary.title}
              </a>
              <span className="text-muted">
                {withSummary.source} · {t('news.reported.excerpt')}
              </span>
            </p>
            {others.length > 0 && (
              <details className="text-sm">
                <summary className="cursor-pointer text-muted">
                  {t('news.reported.allSources', { count: story.items.length })}
                </summary>
                <ul aria-label={t('news.reportedBy')} className="mt-1 space-y-0.5">
                  {story.items.map((i) => (
                    <li key={i.id}>
                      <span className="text-muted">{i.source}: </span>
                      <a
                        href={i.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="underline"
                      >
                        {i.title}
                      </a>
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </Section>
        )}

        <Section title={t('news.impactNow.title')}>
          {a ? (
            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
                <div className="flex items-center gap-2">
                  <div
                    role="img"
                    aria-label={t('news.impactNow.scoreOf', { score: a.impact_score })}
                    className="h-2.5 w-32 overflow-hidden rounded-full bg-border"
                  >
                    <div
                      className={cn(
                        'h-full rounded-full',
                        a.impact_score >= 70
                          ? 'bg-danger'
                          : a.impact_score >= 40
                            ? 'bg-amber-500'
                            : 'bg-primary/50',
                      )}
                      style={{ width: `${Math.max(2, a.impact_score)}%` }}
                    />
                  </div>
                  <span className="text-lg font-semibold tabular-nums">
                    {t('news.impact', { score: a.impact_score })}
                  </span>
                </div>
                {(() => {
                  const d = DIRECTION[a.direction as keyof typeof DIRECTION] ?? DIRECTION.unclear
                  return (
                    <span
                      className={cn('inline-flex items-center gap-1.5 text-sm font-medium', d.text)}
                    >
                      <d.Icon aria-hidden="true" className="h-4 w-4" />
                      {t(`news.direction.${a.direction}`)}
                    </span>
                  )
                })()}
                <span className="text-sm text-muted">{t(`news.horizon.${a.horizon}`)}</span>
                <span className="text-sm text-muted">
                  {t('news.confidence', { level: t(`news.level.${a.confidence}`) })}
                </span>
              </div>
              <p className="text-base leading-relaxed">{a.rationale}</p>
            </div>
          ) : (
            <p className="text-sm text-muted">{t('news.impactNow.notAssessed')}</p>
          )}
        </Section>

        {a && level && (
          <Section title={t('news.outlook.title')}>
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-md border border-border bg-border/30 px-2 py-0.5 text-sm font-medium">
                {t(`news.outlook.term.${a.outlook_term}`)}{' '}
                <span className="font-normal text-muted">
                  ({t(`news.outlook.termHint.${a.outlook_term}`)})
                </span>
              </span>
              <span
                className={cn(
                  'rounded-md border px-2 py-0.5 text-sm font-semibold',
                  LEVEL[level]?.badge,
                )}
              >
                {t(`news.outlook.level.${level}`)}
              </span>
            </div>
            {a.outlook ? (
              <p className="text-base leading-relaxed">{a.outlook}</p>
            ) : (
              <p className="text-sm text-muted">{t('news.outlook.estimated')}</p>
            )}
          </Section>
        )}

        {a?.advice && level !== 'low' && (
          <section
            aria-label={t('news.advice.title')}
            className="space-y-1 rounded-lg border-2 border-primary/50 bg-primary/5 px-4 py-3"
          >
            <h3 className={cn(LABEL, 'flex items-center gap-1.5 text-primary')}>
              <Lightbulb aria-hidden="true" className="h-4 w-4" />
              {t('news.advice.title')}
            </h3>
            <p className="text-base leading-relaxed">{a.advice}</p>
            <p className="text-xs text-muted">{t('news.advice.note')}</p>
          </section>
        )}
      </div>

      <footer className="flex flex-wrap items-center gap-2 border-t border-border bg-border/20 px-5 py-3">
        <Button
          variant="secondary"
          className="min-h-9"
          onClick={() => mark('useful')}
          disabled={feedback.isPending}
          aria-label={`${t('news.useful')}: ${story.title}`}
        >
          {t('news.useful')}
        </Button>
        <Button
          variant="secondary"
          className="min-h-9"
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
      </footer>
      {feedback.isError && (
        <div className="px-5 pb-4">
          <Alert>{errorMessage(feedback.error)}</Alert>
        </div>
      )}
    </article>
  )
}
