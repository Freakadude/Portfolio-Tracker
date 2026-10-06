import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AddWidgetDialog } from './dashboards/AddWidgetDialog'
import { KpiWidget } from './dashboards/widgets/Kpi'
import type { KpiData } from './dashboards/types'
import { GENERAL_US, mockApi, renderAt } from './test-utils'

afterEach(() => vi.unstubAllGlobals())

const LIBRARY = ['kpi', 'allocation', 'note'].map((type) => ({
  type,
  title_key: `widgets.${type}`,
  width: 4,
  height: 3,
  defaults: {},
}))

function openDialog() {
  mockApi({ '/api/v1/dashboard-widgets': LIBRARY, '/api/v1/settings/general': GENERAL_US })
  const onAdd = vi.fn()
  renderAt(<AddWidgetDialog onAdd={onAdd} onClose={() => {}} />)
  return onAdd
}

describe('adding a widget: the search', () => {
  it('lists every widget until something is typed', async () => {
    openDialog()
    expect(await screen.findByRole('button', { name: /^Key figure/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Allocation/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Note/ })).toBeInTheDocument()
  })

  it('finds a figure by its name and adds a Key figure already set to it', async () => {
    const onAdd = openDialog()
    await screen.findByRole('button', { name: /^Key figure/ })
    await userEvent.type(
      screen.getByRole('searchbox', { name: 'Search widgets and figures' }),
      'Return (time-weighted)',
    )
    const figure = screen.getByRole('button', { name: /^Return \(time-weighted\)/ })
    await userEvent.click(figure)
    expect(onAdd).toHaveBeenCalledWith('kpi', { metric: 'twr' })
  })

  it('ignores hyphens, brackets and capitals, and finds XIRR by its short name', async () => {
    const onAdd = openDialog()
    await screen.findByRole('button', { name: /^Key figure/ })
    const box = screen.getByRole('searchbox', { name: 'Search widgets and figures' })
    await userEvent.type(box, 'time weighted')
    expect(screen.getByRole('button', { name: /^Return \(time-weighted\)/ })).toBeInTheDocument()
    await userEvent.clear(box)
    await userEvent.type(box, 'xirr')
    await userEvent.click(screen.getByRole('button', { name: /^Return per year \(XIRR\)/ }))
    expect(onAdd).toHaveBeenCalledWith('kpi', { metric: 'xirr' })
  })

  it('filters the widgets by their description too, and says when nothing matches', async () => {
    openDialog()
    await screen.findByRole('button', { name: /^Key figure/ })
    const box = screen.getByRole('searchbox', { name: 'Search widgets and figures' })
    await userEvent.type(box, 'allocation')
    expect(screen.getByRole('button', { name: /^Allocation/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Note/ })).not.toBeInTheDocument()
    await userEvent.clear(box)
    await userEvent.type(box, 'zzzz')
    expect(screen.getByRole('status')).toHaveTextContent('Nothing matches "zzzz"')
  })
})

const START = { date: '2024-01-02', kind: 'start', amount: '-1000.00' }
const FLOWS = [
  START,
  { date: '2024-03-01', kind: 'put_in', amount: '-500.00' },
  { date: '2024-06-14', kind: 'received', amount: '12.50' },
  { date: '2024-12-31', kind: 'end', amount: '1700.00' },
]

function kpi(over: Partial<KpiData>): KpiData {
  return {
    metric: 'twr',
    kind: 'pct',
    value: '0.1',
    sparkline: [],
    start: '2024-01-02',
    end: '2024-12-31',
    ...over,
  }
}

describe('how a return is calculated', () => {
  it('has no explanation for a figure that is not a return', () => {
    mockApi({ '/api/v1/settings/general': GENERAL_US })
    renderAt(<KpiWidget data={kpi({ metric: 'value', kind: 'eur' })} config={{}} filters={{}} />)
    expect(screen.queryByRole('button', { name: 'How is this calculated?' })).toBeNull()
  })

  it('shows the stretches of the time-weighted return and what they multiply to', async () => {
    mockApi({ '/api/v1/settings/general': GENERAL_US })
    const data = kpi({
      value: '0.155',
      breakdown: {
        kind: 'twr',
        segments: [
          {
            start: '2024-01-03',
            end: '2024-03-01',
            flow: '0',
            start_capital: '1000.00',
            end_value: '1100.00',
            income: '0',
            ratio: '1.1',
          },
          {
            start: '2024-03-02',
            end: '2024-12-31',
            flow: '500.00',
            start_capital: '1600.00',
            end_value: '1700.00',
            income: '12.50',
            ratio: '1.05',
          },
        ],
      },
    })
    renderAt(<KpiWidget data={data} config={{}} filters={{}} />)
    await userEvent.click(screen.getByRole('button', { name: 'How is this calculated?' }))
    const dialog = screen.getByRole('dialog', {
      name: 'How the time-weighted return is calculated',
    })
    expect(within(dialog).getByText('Period: 2024-01-02 to 2024-12-31')).toBeInTheDocument()
    const table = within(dialog).getByRole('table', {
      name: 'The stretches of the period and the growth of each',
    })
    expect(within(table).getAllByRole('row')).toHaveLength(4) // header, two stretches, the total
    expect(within(table).getByText('€1,100.00')).toBeInTheDocument()
    expect(within(table).getByText('10.00%')).toBeInTheDocument() // the first stretch: 1.1 - 1
    expect(within(table).getByText('5.00%')).toBeInTheDocument() // the second: 1.05 - 1
    expect(within(table).getByRole('row', { name: /All stretches together/ })).toHaveTextContent(
      '15.50%',
    ) // 1.1 x 1.05 - 1, the figure on the tile
  })

  it('lists the money flows of the XIRR and copies them for a spreadsheet', async () => {
    mockApi({ '/api/v1/settings/general': GENERAL_US })
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } })
    renderAt(
      <KpiWidget
        data={kpi({ metric: 'xirr', value: '0.12', breakdown: { kind: 'xirr', flows: FLOWS } })}
        config={{}}
        filters={{}}
      />,
    )
    await userEvent.click(screen.getByRole('button', { name: 'How is this calculated?' }))
    const dialog = screen.getByRole('dialog', {
      name: 'How the return per year (XIRR) is calculated',
    })
    const table = within(dialog).getByRole('table', { name: 'The money flows used for the XIRR' })
    expect(within(table).getByRole('row', { name: /Money put in.*500/ })).toBeInTheDocument()
    expect(within(table).getByRole('row', { name: /Value at the end.*1,700/ })).toBeInTheDocument()
    expect(within(table).getByRole('row', { name: /yearly rate/ })).toHaveTextContent('12.00%')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Copy for a spreadsheet' }))
    expect(writeText).toHaveBeenCalledWith(
      'date\tamount\n2024-01-02\t-1000.00\n2024-03-01\t-500.00\n2024-06-14\t12.50\n2024-12-31\t1700.00',
    )
    expect(await screen.findByText('Copied. Paste it into a spreadsheet.')).toBeInTheDocument()
  })
})
