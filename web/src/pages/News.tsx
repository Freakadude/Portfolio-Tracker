import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'
import { errorMessage } from '../api/client'
import { useInstruments } from '../api/queries'
import { EmptyState } from '../components/display'
import { Alert, Field, Input, Select } from '../components/ui'
import { useNews, useNewsSources, type NewsFilters } from '../news/api'
import { StoryCard } from '../news/StoryCard'

/** The News page (FR-NW-07): stories linked to what you hold, filtered by holding (directly or
 * through an ETF), impact, direction, source and date. */
export function News() {
  const { t } = useTranslation()
  const [params] = useSearchParams()
  const [filters, setFilters] = useState<NewsFilters>({ sort: 'time' })
  const instruments = useInstruments('all')
  const sources = useNewsSources()
  const news = useNews(filters)
  const set = (patch: Partial<NewsFilters>) => setFilters((f) => ({ ...f, ...patch }))
  const focus = params.get('cluster')
  const stories = (news.data?.clusters ?? [])
    .slice()
    .sort((a, b) =>
      focus && String(a.id) === focus ? -1 : focus && String(b.id) === focus ? 1 : 0,
    )
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">{t('news.title')}</h1>
      <form
        aria-label={t('news.filters')}
        className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4"
        onSubmit={(e) => e.preventDefault()}
      >
        <Field label={t('news.filter.holding')}>
          {(p) => (
            <Select
              value={filters.instrument ?? ''}
              onChange={(e) =>
                set({ instrument: e.target.value ? Number(e.target.value) : undefined })
              }
              {...p}
            >
              <option value="">{t('news.filter.all')}</option>
              {(instruments.data ?? []).map((i) => (
                <option key={i.id} value={i.id}>
                  {i.name}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label={t('news.filter.impact')}>
          {(p) => (
            <Select
              value={filters.minImpact ?? 0}
              onChange={(e) => set({ minImpact: Number(e.target.value) })}
              {...p}
            >
              {[0, 30, 50, 70].map((n) => (
                <option key={n} value={n}>
                  {n === 0 ? t('news.filter.anyImpact') : t('news.filter.atLeast', { n })}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label={t('news.filter.direction')}>
          {(p) => (
            <Select
              value={filters.direction ?? ''}
              onChange={(e) => set({ direction: e.target.value || undefined })}
              {...p}
            >
              <option value="">{t('news.filter.all')}</option>
              {['positive', 'negative', 'mixed', 'unclear'].map((d) => (
                <option key={d} value={d}>
                  {t(`news.direction.${d}`)}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label={t('news.filter.source')}>
          {(p) => (
            <Select
              value={filters.source ?? ''}
              onChange={(e) => set({ source: e.target.value ? Number(e.target.value) : undefined })}
              {...p}
            >
              <option value="">{t('news.filter.all')}</option>
              {(sources.data ?? []).map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label={t('news.filter.from')}>
          {(p) => (
            <Input
              type="date"
              value={filters.from ?? ''}
              onChange={(e) => set({ from: e.target.value })}
              {...p}
            />
          )}
        </Field>
        <Field label={t('news.filter.to')}>
          {(p) => (
            <Input
              type="date"
              value={filters.to ?? ''}
              onChange={(e) => set({ to: e.target.value })}
              {...p}
            />
          )}
        </Field>
        <Field label={t('news.filter.sort')}>
          {(p) => (
            <Select
              value={filters.sort ?? 'time'}
              onChange={(e) => set({ sort: e.target.value as NewsFilters['sort'] })}
              {...p}
            >
              {['time', 'relevance', 'impact'].map((s) => (
                <option key={s} value={s}>
                  {t(`news.sort.${s}`)}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <label className="flex items-end gap-2 pb-2 text-sm">
          <input
            type="checkbox"
            checked={filters.includeUnlinked ?? false}
            onChange={(e) => set({ includeUnlinked: e.target.checked })}
          />
          {t('news.filter.unlinked')}
        </label>
      </form>
      {news.isError && <Alert>{errorMessage(news.error)}</Alert>}
      {news.isSuccess && stories.length === 0 && (
        <EmptyState title={t('news.empty.title')} body={t('news.empty.body')} />
      )}
      <div className="space-y-3">
        {stories.map((s) => (
          <StoryCard key={s.id} story={s} />
        ))}
      </div>
      {news.data && news.data.total > stories.length && (
        <p className="text-sm text-muted">
          {t('news.showing', { shown: stories.length, total: news.data.total })}
        </p>
      )}
    </div>
  )
}
