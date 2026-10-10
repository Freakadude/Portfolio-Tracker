import { screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { StoryCard } from './news/StoryCard'
import type { NewsCluster } from './news/api'
import { GENERAL_US, mockApi, renderAt } from './test-utils'

afterEach(() => vi.unstubAllGlobals())

const link = (over: Record<string, unknown>) => ({
  id: 1,
  link_type: 'direct',
  instrument_id: 2,
  sleeve: null,
  label: 'ASML Holding',
  weight_pct: null,
  relevance: '0.8',
  matched_by: 'isin:NL0010273215',
  held: true,
  portfolio_weight_pct: '12.5',
  reason: null,
  ...over,
})

const story = (over: Record<string, unknown> = {}): NewsCluster =>
  ({
    id: 21,
    title: 'Export limits on chip tools widen',
    first_seen: '2026-10-09T07:00:00Z',
    last_seen: '2026-10-09T09:00:00Z',
    relevance: '0.7',
    items: [
      {
        id: 1,
        source: 'Wire',
        title: 'Export limits widen',
        summary: 'The government widened limits on exports of chip-making tools.',
        url: 'https://wire.example/a',
        published: '2026-10-09T07:00:00Z',
      },
    ],
    links: [link({})],
    assessment: {
      impact_score: 74,
      direction: 'negative',
      horizon: 'weeks',
      affected: ['ASML Holding'],
      rationale: 'Orders for the direct holding could be cut.',
      confidence: 'medium',
      model: 'claude-sonnet-5-5',
      outlook_term: 'mid',
      outlook_level: 'high',
      outlook: 'Orders could fall over the coming quarters, also through the World ETF.',
      advice: 'Watch the gold sleeve drift; consider directing new money elsewhere first.',
    },
    ...over,
  }) as unknown as NewsCluster

const show = (s: NewsCluster) => {
  mockApi({ '/api/v1/settings/general': GENERAL_US })
  renderAt(<StoryCard story={s} />)
  return screen.getByRole('article', { name: s.title })
}

describe('a story card (ADR 0061)', () => {
  it('tells direct, through-a-fund, indirect and watched apart by their wording', () => {
    const card = show(
      story({
        links: [
          link({ id: 1 }),
          link({
            id: 2,
            link_type: 'look_through',
            instrument_id: 1,
            label: 'World ETF',
            weight_pct: '5.2',
            matched_by: 'constituent:apple inc',
            portfolio_weight_pct: '40',
          }),
          link({
            id: 3,
            link_type: 'theme',
            instrument_id: null,
            sleeve: 'gold_hedge',
            label: 'gold_hedge',
            matched_by: 'llm:theme:chip tools',
            reason: 'chip tools',
            held: true,
            portfolio_weight_pct: null,
          }),
          link({
            id: 4,
            instrument_id: 9,
            label: 'Nvidia',
            held: false,
            portfolio_weight_pct: null,
          }),
        ],
      }),
    )
    const direct = within(card).getByRole('list', { name: 'Hits your holding directly' })
    expect(within(direct).getByText('ASML Holding')).toBeVisible()
    expect(within(direct).getByText(/12[.,]5 % of your portfolio/)).toBeVisible()
    const fund = within(card).getByRole('list', { name: 'Reaches you through a fund' })
    expect(within(fund).getByText('World ETF')).toBeVisible()
    expect(within(fund).getByText(/Apple Inc is 5[.,]2 % of the fund/)).toBeVisible()
    const indirect = within(card).getByRole('list', { name: 'Might affect you indirectly' })
    expect(within(indirect).getByText('gold_hedge sleeve')).toBeVisible()
    expect(within(indirect).getByText('through a theme')).toBeVisible()
    expect(within(indirect).getByText('because chip tools')).toBeVisible()
    const watched = within(card).getByRole('list', { name: 'Touches something you only watch' })
    expect(within(watched).getByText('Nvidia')).toBeVisible()
    expect(within(watched).getByText('watchlist')).toBeVisible()
  })

  it('separates the title, what was reported, the impact, the outlook and the advice', () => {
    const card = show(story())
    expect(within(card).getByRole('heading', { level: 2 })).toHaveTextContent(
      'Export limits on chip tools widen',
    )
    const reported = within(card).getByRole('region', { name: 'What was reported' })
    expect(within(reported).getByText(/widened limits on exports/)).toBeVisible()
    expect(within(reported).getByText(/Summary from the source/)).toBeVisible()
    expect(within(reported).getByRole('link', { name: 'Export limits widen' })).toHaveAttribute(
      'href',
      'https://wire.example/a',
    )
    const impact = within(card).getByRole('region', { name: 'Impact now' })
    expect(within(impact).getByText('Impact 74')).toBeVisible()
    expect(within(impact).getByText('Negative')).toBeVisible() // a word, not only a colour
    expect(within(impact).getByText(/Orders for the direct holding could be cut/)).toBeVisible()
    const outlook = within(card).getByRole('region', { name: 'What could happen' })
    expect(within(outlook).getByText(/Mid term/)).toBeVisible()
    expect(within(outlook).getByText('High potential')).toBeVisible()
    expect(within(outlook).getByText(/Orders could fall/)).toBeVisible()
    const advice = within(card).getByRole('region', { name: 'What you could do' })
    expect(within(advice).getByText(/consider directing new money elsewhere/)).toBeVisible()
    expect(within(advice).getByText(/Not an order/)).toBeVisible()
  })

  it('has advice only for a mid or high potential', () => {
    const base = story().assessment as object
    const card = show(
      story({ assessment: { ...base, outlook_level: 'low', advice: 'Do not show this.' } }),
    )
    expect(within(card).getByText('Low potential')).toBeVisible()
    expect(within(card).queryByRole('region', { name: 'What you could do' })).toBeNull()
  })

  it('says the term and potential are estimated for an assessment without an outlook text', () => {
    const base = story().assessment as object
    const card = show(story({ assessment: { ...base, outlook: null, advice: null } }))
    expect(within(card).getByText(/estimated from the score and the horizon/)).toBeVisible()
    expect(within(card).queryByRole('region', { name: 'What you could do' })).toBeNull()
  })

  it('says so when a story has not been assessed yet and keeps the links', () => {
    const card = show(story({ assessment: null }))
    expect(within(card).getByText('Not assessed yet.')).toBeVisible()
    expect(within(card).queryByRole('region', { name: 'What could happen' })).toBeNull()
    expect(within(card).getByRole('list', { name: 'Hits your holding directly' })).toBeVisible()
  })

  it('shows the source summary as given and marks a headline-only story', () => {
    const item = (story().items as unknown as Record<string, unknown>[])[0]
    const card = show(story({ items: [{ ...item, summary: '' }] }))
    expect(within(card).getByText('The source gave only the headline.')).toBeVisible()
  })
})
