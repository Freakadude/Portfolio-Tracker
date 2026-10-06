import { screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { JobStatus } from './system/JobStatus'
import { GENERAL_US, mockApi, renderAt } from './test-utils'

afterEach(() => vi.unstubAllGlobals())

const iso = (offsetMs = 0) => new Date(Date.now() + offsetMs).toISOString()
const request = (status: string, over: Record<string, unknown> = {}) => ({
  id: 5,
  job: 'macro',
  params: {},
  status,
  created_at: iso(-1000),
  finished_at: status === 'done' || status === 'failed' ? iso() : null,
  error: null,
  ...over,
})
const jobs = (requests: unknown[], runs: unknown[] = []) => ({ requests, runs, available: {} })
const pressed = { isSuccess: true, submittedAt: Date.now() }

describe('progress of background work (FR-SY-09)', () => {
  it('shows nothing until the button has worked', () => {
    mockApi({ '/api/v1/settings/general': GENERAL_US })
    renderAt(<JobStatus jobs={['macro']} from={{ isSuccess: false, submittedAt: Date.now() }} />)
    expect(screen.queryByRole('status')).toBeNull()
  })

  it('follows the work from waiting to running to done, with the last line of its log', async () => {
    let state: unknown = jobs([request('pending')])
    mockApi({ '/api/v1/settings/general': GENERAL_US, '/api/v1/system/jobs': () => state })
    renderAt(<JobStatus jobs={['macro']} from={pressed} />)
    expect(await screen.findByText(/Waiting for the worker/)).toBeInTheDocument()
    expect(screen.getByTestId('job-progress')).toBeInTheDocument() // something moves while it waits
    state = jobs([request('running')])
    expect(
      await screen.findByText(/The worker is on it/, {}, { timeout: 4000 }),
    ).toBeInTheDocument()
    state = jobs(
      [request('done')],
      [
        {
          id: 9,
          job: 'macro',
          status: 'ok',
          params: {},
          started_at: iso(-500),
          finished_at: iso(),
          log: 'Fetching DFII10\nDFII10: 3 new points',
        },
      ],
    )
    expect(await screen.findByText(/Finished at/, {}, { timeout: 4000 })).toBeInTheDocument()
    expect(screen.getByText('DFII10: 3 new points')).toBeInTheDocument()
    expect(screen.queryByTestId('job-progress')).toBeNull() // finished: the bar is gone
  })

  it('says why the work failed', async () => {
    mockApi({
      '/api/v1/settings/general': GENERAL_US,
      '/api/v1/system/jobs': jobs([request('failed', { error: 'FRED rejected the key' })]),
    })
    renderAt(<JobStatus jobs={['macro']} from={pressed} />)
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'It did not work: FRED rejected the key',
    )
  })

  it('ignores other jobs and work that was finished long before the button was pressed', async () => {
    mockApi({
      '/api/v1/settings/general': GENERAL_US,
      '/api/v1/system/jobs': jobs([
        request('done', { id: 4, created_at: iso(-3_600_000) }),
        request('failed', { id: 6, job: 'news', error: 'not this one' }),
      ]),
    })
    renderAt(<JobStatus jobs={['macro']} from={pressed} />)
    expect(await screen.findByText(/Asking the worker to start/)).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('runs its callback once when the work has finished', async () => {
    const done = vi.fn()
    mockApi({
      '/api/v1/settings/general': GENERAL_US,
      '/api/v1/system/jobs': jobs([request('done')]),
    })
    renderAt(<JobStatus jobs={['macro']} from={pressed} onDone={done} />)
    await screen.findByText(/Finished at/)
    expect(done).toHaveBeenCalledTimes(1)
  })
})
