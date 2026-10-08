import { screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Containers } from './notify/Containers'
import { GENERAL_US, mockApi, renderAt } from './test-utils'

afterEach(() => vi.unstubAllGlobals())

const SHA = '98466054e11abcdef0123456789abcdef0123456'
const container = (over: Record<string, unknown> = {}) => ({
  build: SHA,
  started_at: '2026-10-08T06:00:00Z',
  uptime_seconds: 3 * 3600 + 12 * 60,
  seen_seconds_ago: null,
  alive: true,
  ...over,
})
const show = (web: object, worker: object | null) => {
  mockApi({ '/api/v1/settings/general': GENERAL_US })
  return renderAt(<Containers web={web as never} worker={worker as never} />)
}

describe('which commit each container runs, and for how long (FR-SY-10)', () => {
  it('names the commit with a link to it and says how long the web container has run', () => {
    show(container(), container({ uptime_seconds: 125, seen_seconds_ago: 5 }))
    const web = within(screen.getByTestId('web'))
    const link = web.getByRole('link', { name: 'Commit 9846605' })
    expect(link).toHaveAttribute(
      'href',
      `https://github.com/Freakadude/Portfolio-Tracker/commit/${SHA}`,
    )
    expect(link).toHaveAttribute('title', SHA)
    expect(web.getByText('Running for 3 h 12 min')).toBeInTheDocument()
    expect(within(screen.getByTestId('worker')).getByText('Running for 2 min')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull() // same build, worker alive
  })

  it('counts days for a long run and seconds for a fresh start', () => {
    show(
      container({ uptime_seconds: 2 * 86400 + 4 * 3600 + 30 * 60 }),
      container({ uptime_seconds: 40 }),
    )
    expect(screen.getByText('Running for 2 d 4 h')).toBeInTheDocument()
    expect(screen.getByText('Running for 40 s')).toBeInTheDocument()
  })

  it('warns when the two containers run different builds', () => {
    show(container(), container({ build: 'a'.repeat(40) }))
    expect(screen.getByRole('alert')).toHaveTextContent(/run different builds/)
  })

  it('says when the worker has gone quiet, and when it has not reported at all', () => {
    const first = show(container(), container({ alive: false, seen_seconds_ago: 600 }))
    expect(screen.getByText(/Not heard from for 10 min: the worker may have stopped/)).toBeVisible()
    first.unmount()
    show(container(), null)
    expect(screen.getByText(/No report from the worker yet/)).toBeVisible()
  })

  it('says it is a development build when there is no commit', () => {
    show(container({ build: null }), null)
    expect(
      within(screen.getByTestId('web')).getByText('Development build (no commit)'),
    ).toBeVisible()
    expect(screen.queryByRole('link')).toBeNull()
  })
})
