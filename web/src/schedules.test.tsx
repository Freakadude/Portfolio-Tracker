import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SchedulesTab } from './system/SchedulesTab'
import { GENERAL_US, mockApi, problem, renderAt } from './test-utils'

afterEach(() => vi.unstubAllGlobals())

const item = (over: Record<string, unknown> = {}) => ({
  job_id: 'snapshots',
  title: 'Value snapshots',
  what: "Saves the day's portfolio value and positions.",
  normal: 'every day at 23:00',
  normal_cron: '0 23 * * *',
  cron: '0 23 * * *',
  changed: false,
  timezone: 'Europe/Amsterdam',
  next_run: '2026-10-06T21:00:00Z',
  ...over,
})
const listing = (items: unknown[]) => ({
  timezone: 'Europe/Amsterdam',
  items,
  fixed: ['Closing prices of XETR: two hours after the exchange closes, on trading days'],
  examples: [
    { cron: '0 22 * * *', words: 'every day at 22:00' },
    { cron: '30 19 * * mon-fri', words: 'weekdays at 19:30' },
  ],
})

describe('schedules (FR-SY-09)', () => {
  it('lists each job with what it does, when it runs normally and next, and what cannot move', async () => {
    mockApi({
      '/api/v1/settings/general': GENERAL_US,
      '/api/v1/schedules': listing([item()]),
    })
    renderAt(<SchedulesTab />)
    const row = (await screen.findByText('Value snapshots')).closest('tr') as HTMLElement
    expect(within(row).getByText(/Saves the day/)).toBeInTheDocument()
    expect(within(row).getByText('every day at 23:00')).toBeInTheDocument()
    expect(within(row).getByText('as normal')).toBeInTheDocument()
    expect(within(row).getByText(/6 Oct 2026, 23:00/)).toBeInTheDocument() // the owner's time zone
    expect(screen.getByText(/Closing prices of XETR/)).toBeInTheDocument()
    // the examples are written out in the help
    await userEvent.click(screen.getByText('How do I change a time? Examples'))
    expect(screen.getByText('30 19 * * mon-fri')).toBeInTheDocument()
  })

  it('changes a time from an example and saves it', async () => {
    const { calls } = mockApi({
      '/api/v1/settings/general': GENERAL_US,
      'GET /api/v1/schedules': listing([item()]),
      'PUT /api/v1/schedules/snapshots': item({ cron: '30 19 * * mon-fri', changed: true }),
    })
    renderAt(<SchedulesTab />)
    await userEvent.click(
      await screen.findByRole('button', { name: 'Change the time of Value snapshots' }),
    )
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: 'weekdays at 19:30' }))
    expect(within(dialog).getByLabelText('Time')).toHaveValue('30 19 * * mon-fri')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save time' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PUT')).toBe(true))
    expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({ cron: '30 19 * * mon-fri' })
  })

  it('shows the reason when a time is refused, and can put a changed one back', async () => {
    const { calls } = mockApi({
      '/api/v1/settings/general': GENERAL_US,
      'GET /api/v1/schedules': listing([item({ cron: '0 8 * * *', changed: true })]),
      'PUT /api/v1/schedules/snapshots': (request: Request) =>
        request.headers.get('content-length') === '13'
          ? item()
          : problem(422, 'Invalid schedule', 'Write the weekday as a name, such as mon-fri.'),
    })
    renderAt(<SchedulesTab />)
    expect(await screen.findByText('set by you')).toBeInTheDocument()
    await userEvent.click(
      screen.getByRole('button', { name: 'Change the time of Value snapshots' }),
    )
    const dialog = await screen.findByRole('dialog')
    await userEvent.clear(within(dialog).getByLabelText('Time'))
    await userEvent.type(within(dialog).getByLabelText('Time'), '0 8 * * 1')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save time' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent(
      'Write the weekday as a name',
    )
    await userEvent.click(within(dialog).getByRole('button', { name: 'Close' }))
    await userEvent.click(
      screen.getByRole('button', { name: 'Put Value snapshots back to its normal time' }),
    )
    await waitFor(() => expect(calls.filter((c) => c.method === 'PUT').length).toBe(2))
    expect(calls.filter((c) => c.method === 'PUT')[1].body).toEqual({ cron: null })
  })
})
