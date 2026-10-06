import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { News } from './pages/News'
import { GENERAL_US, mockApi, renderAt } from './test-utils'

afterEach(() => vi.unstubAllGlobals())

const event = (over: Record<string, unknown>) => ({
  id: 1,
  kind: 'central_bank',
  date: '2026-10-28',
  in_days: 22,
  title: 'Federal Reserve (FOMC) rate decision',
  instrument_id: null,
  instrument_name: null,
  source: 'shipped',
  detail: '',
  brief_done: false,
  ...over,
})

const EVENTS = [
  event({}),
  event({
    id: 2,
    kind: 'earnings',
    date: '2026-10-14',
    in_days: 8,
    title: 'ASML Holding reports earnings',
    instrument_id: 5,
    instrument_name: 'ASML Holding',
    source: 'eodhd',
    detail: 'before the market opens, expected earnings per share 5.32',
  }),
  event({
    id: 3,
    kind: 'custom',
    date: '2026-10-07',
    in_days: 1,
    title: 'Annual meeting',
    source: 'owner',
  }),
]

const routes = (events: unknown = EVENTS) => ({
  '/api/v1/settings/general': GENERAL_US,
  '/api/v1/settings/calendar': { earnings_eodhd: false, earnings_days: 60 },
  '/api/v1/calendar/events': events,
  '/api/v1/instruments': [],
  '/api/v1/news': { clusters: [], next_cursor: null },
  '/api/v1/news/sources': [],
})

const show = () => renderAt(<News />, '/news?tab=calendar')

describe('the calendar tab (FR-NW-09)', () => {
  it('lists what is coming with its source and what it is about', async () => {
    mockApi(routes())
    show()
    const table = await screen.findByRole('table', { name: 'Dated events in the next 90 days' })
    const fed = within(table).getByRole('row', { name: /Federal Reserve/ })
    expect(fed).toHaveTextContent('2026-10-28')
    expect(fed).toHaveTextContent('in 22 days')
    expect(fed).toHaveTextContent('Ready-made')
    const asml = within(table).getByRole('row', { name: /ASML Holding reports earnings/ })
    expect(asml).toHaveTextContent('EODHD')
    expect(asml).toHaveTextContent('expected earnings per share 5.32')
    expect(within(table).getByRole('row', { name: /Annual meeting/ })).toHaveTextContent('in 1 day')
    expect(screen.getByText(/check them against ecb.europa.eu/)).toBeInTheDocument()
  })

  it('says so when nothing is coming up', async () => {
    mockApi(routes([]))
    show()
    expect(await screen.findByText(/No dated events in the next 90 days/)).toBeInTheDocument()
  })

  it('adds an event of your own', async () => {
    const { calls } = mockApi({
      ...routes(),
      'POST /api/v1/calendar/events': event({ id: 9, title: 'Tax deadline', source: 'owner' }),
    })
    show()
    await userEvent.click(await screen.findByRole('button', { name: 'Add an event' }))
    const dialog = await screen.findByRole('dialog', { name: 'Add an event' })
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save event' }))
    expect(await within(dialog).findAllByText('This is required.')).toHaveLength(2)
    await userEvent.type(within(dialog).getByLabelText('Title'), 'Tax deadline')
    await userEvent.type(within(dialog).getByLabelText('Date'), '2026-12-31')
    await userEvent.type(within(dialog).getByLabelText('Note (optional)'), 'file the return')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save event' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(
      calls.find((c) => c.method === 'POST' && c.path === '/api/v1/calendar/events')?.body,
    ).toEqual({
      title: 'Tax deadline',
      date: '2026-12-31',
      kind: 'custom',
      instrument_id: null,
      detail: 'file the return',
    })
  })

  it('changes a date, and deletes after asking', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const { calls } = mockApi({
      ...routes(),
      'PATCH /api/v1/calendar/events/3': event({ id: 3, date: '2026-10-08' }),
      'DELETE /api/v1/calendar/events/1': null,
    })
    show()
    await userEvent.click(await screen.findByRole('button', { name: 'Change Annual meeting' }))
    const dialog = await screen.findByRole('dialog', { name: 'Change an event' })
    expect(within(dialog).getByLabelText('Title')).toHaveValue('Annual meeting')
    await userEvent.clear(within(dialog).getByLabelText('Date'))
    await userEvent.type(within(dialog).getByLabelText('Date'), '2026-10-08')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save event' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(calls.find((c) => c.method === 'PATCH')?.body).toMatchObject({ date: '2026-10-08' })

    await userEvent.click(
      screen.getByRole('button', { name: 'Delete Federal Reserve (FOMC) rate decision' }),
    )
    await waitFor(() => expect(calls.some((c) => c.method === 'DELETE')).toBe(true))
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('2026-10-28'))
    confirm.mockRestore()
  })

  it('asks the worker to refresh the dates', async () => {
    const { calls } = mockApi({ ...routes(), 'POST /api/v1/calendar/refresh': { queued: true } })
    show()
    await userEvent.click(await screen.findByRole('button', { name: 'Refresh dates' }))
    expect(await screen.findByText(/Asking the worker to start/)).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'POST' && c.path === '/api/v1/calendar/refresh')).toBe(
      true,
    )
  })

  it('shows the stories by default and the calendar from its tab', async () => {
    mockApi(routes())
    renderAt(<News />, '/news')
    expect(await screen.findByRole('form', { name: 'Filter the news' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: 'Calendar' }))
    expect(await screen.findByRole('table', { name: /Dated events/ })).toBeInTheDocument()
    expect(screen.queryByRole('form', { name: 'Filter the news' })).not.toBeInTheDocument()
  })
})
