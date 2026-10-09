import { screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { KPI_METRICS } from './dashboards/registry'
import { KpiWidget, kpiTarget } from './dashboards/widgets/Kpi'
import { GENERAL_US, mockApi, renderAt } from './test-utils'

afterEach(() => vi.unstubAllGlobals())

const day = {
  metric: 'latest_price',
  kind: 'price' as const,
  value: '107.9',
  currency: 'EUR',
  instrument_id: 4,
  name: 'World fund',
  label: 'Delayed price of 2024-01-15 10:30 (yahoo)',
  change_ratio: '-0.000926',
  note: 'Session of 2024-01-15, previous close 108.00',
  intraday: true,
  baseline: '108',
  sparkline: [
    { date: '2024-01-15T00:00:00', value: '108' },
    { date: '2024-01-15T09:00:00', value: '109' },
    { date: '2024-01-15T10:30:00', value: '107.9' },
  ],
}

describe('the key figure "latest price"', () => {
  it('is one of the figures to choose from', () => {
    expect(KPI_METRICS).toContain('latest_price')
  })

  it('shows the price in its currency with two decimals, the change and the day chart', () => {
    mockApi({ '/api/v1/settings/general': GENERAL_US })
    renderAt(<KpiWidget data={day} config={{ title: 'World fund' }} filters={{}} />)
    expect(screen.getByText(/107[.,]90 EUR/)).toBeVisible()
    expect(screen.getByText('Latest price')).toBeVisible()
    expect(screen.getByText('Delayed price of 2024-01-15 10:30 (yahoo)')).toBeVisible()
    expect(screen.getByText('Session of 2024-01-15, previous close 108.00')).toBeVisible()
    // down a little on the close before; the sign and the arrow are read out too
    expect(screen.getByText(/0[.,]09\s?%/)).toBeVisible()
    expect(
      screen.getByRole('img', { name: 'Price over the day, dotted line: the close before' }),
    ).toBeVisible()
    expect(screen.getByTestId('baseline')).toBeInTheDocument()
  })

  it('draws a period chart without the dotted line, and opens the position when clicked', () => {
    mockApi({ '/api/v1/settings/general': GENERAL_US })
    renderAt(
      <KpiWidget
        data={{ ...day, intraday: undefined, baseline: undefined, note: undefined }}
        config={{}}
        filters={{}}
      />,
    )
    expect(screen.getByRole('img', { name: 'Trend over the period' })).toBeVisible()
    expect(screen.queryByTestId('baseline')).toBeNull()
    expect(screen.getByRole('link')).toHaveAttribute('href', '/holdings/4')
    expect(kpiTarget('latest_price', 4)).toBe('/holdings/4')
    expect(kpiTarget('value')).toBe('/holdings')
  })

  it('says what to choose when there is no holding', () => {
    mockApi({ '/api/v1/settings/general': GENERAL_US })
    renderAt(
      <KpiWidget
        data={{
          metric: 'latest_price',
          kind: 'price',
          value: null,
          sparkline: [],
          empty: true,
          reason: 'Choose a holding (scope: Instrument) to see its latest price.',
        }}
        config={{}}
        filters={{}}
      />,
    )
    expect(screen.getByText(/Choose a holding/)).toBeVisible()
  })
})
