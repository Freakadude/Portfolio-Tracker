import { screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { HoldingsTableWidget } from './dashboards/widgets/Composition'
import type { HoldingsData } from './dashboards/types'
import { GENERAL_US, mockApi, renderAt } from './test-utils'

afterEach(() => vi.unstubAllGlobals())

const row = (id: number, name: string, over: Record<string, unknown> = {}) => ({
  instrument_id: id,
  name,
  account: 'Degiro',
  asset_class: 'ETF',
  sleeve: null,
  quantity: '10',
  close: '100',
  close_date: '2026-10-05',
  latest: null,
  latest_at: null,
  target_weight: null,
  weight_diff: null,
  stale: false,
  value: '1000',
  weight: '0.5',
  unrealized: '0',
  unrealized_ratio: null,
  day: '0',
  day_ratio: null,
  total_return: '0',
  income: '0',
  ...over,
})

const data = (rows: unknown[], over: Partial<HoldingsData> = {}) =>
  ({
    columns: ['name', 'close', 'latest', 'weight'],
    group_by: 'none',
    rows,
    ...over,
  }) as HoldingsData

function show(d: HoldingsData, config: Record<string, unknown> = {}) {
  mockApi({ '/api/v1/settings/general': GENERAL_US })
  return renderAt(<HoldingsTableWidget data={d} config={config} filters={{}} />)
}

const names = () =>
  screen
    .getAllByRole('row')
    .slice(1)
    .map((r) => within(r).getByRole('link').textContent)

describe('the holdings widget (FR-DB-03)', () => {
  it('shows the columns in the order they were chosen', () => {
    show(data([row(1, 'A')], { columns: ['weight', 'name', 'close'] }))
    expect(screen.getAllByRole('columnheader').map((h) => h.textContent)).toEqual([
      'Weight',
      'Instrument',
      'Last close',
    ])
  })

  it('sorts by the chosen column, either way, with missing values last', () => {
    const rows = [
      row(1, 'Low', { weight: '0.1' }),
      row(2, 'High', { weight: '0.7' }),
      row(3, 'None', { weight: null }),
      row(4, 'Mid', { weight: '0.4' }),
    ]
    const first = show(data(rows, { columns: ['name', 'weight'] }), {
      sort_by: 'weight',
      sort_dir: 'desc',
    })
    expect(names()).toEqual(['High', 'Mid', 'Low', 'None'])
    first.unmount()
    show(data(rows, { columns: ['name', 'weight'] }), { sort_by: 'weight', sort_dir: 'asc' })
    expect(names()).toEqual(['Low', 'Mid', 'High', 'None'])
  })

  it('shows the target weight, the difference to it, and the latest price when there is one', () => {
    show(
      data(
        [
          row(1, 'Core', {
            target_weight: '0.6',
            weight: '0.7',
            weight_diff: '0.1',
            latest: '101.5',
            latest_at: '2026-10-06T13:20:00Z',
          }),
          row(2, 'Plain'),
        ],
        { columns: ['name', 'latest', 'weight', 'target_weight', 'weight_diff'] },
      ),
    )
    const core = screen.getByRole('row', { name: /Core/ })
    expect(within(core).getByText(/101[.,]50/)).toBeInTheDocument()
    expect(within(core).getByText(/60[.,]0s?%/)).toBeInTheDocument()
    expect(within(core).getByText(/10[.,]00\s?%/)).toBeInTheDocument()
    const plain = screen.getByRole('row', { name: /Plain/ })
    expect(within(plain).getAllByText('–').length).toBeGreaterThanOrEqual(2) // no target, no diff
  })
})

describe('instrument types look different (FR-INS-02)', () => {
  it('marks each holding with its type, in words and in a colour of its own', () => {
    show(
      data(
        [
          row(1, 'World ETF'),
          row(2, 'Chip Maker', { asset_class: 'EQUITY' }),
          row(3, 'Gold', { asset_class: 'ETC' }),
        ],
        { columns: ['name'] },
      ),
    )
    const badge = (name: RegExp) =>
      screen.getByRole('row', { name }).querySelector<HTMLElement>('[data-asset-class]')
    expect(badge(/World ETF/)).toHaveAttribute('data-asset-class', 'ETF')
    expect(badge(/Chip Maker/)).toHaveAttribute('data-asset-class', 'EQUITY')
    expect(badge(/Chip Maker/)).toHaveTextContent('Equity')
    const classes = [/World ETF/, /Chip Maker/, /Gold/].map((n) => badge(n)?.className)
    expect(new Set(classes).size).toBe(3) // three types, three different looks
  })
})
