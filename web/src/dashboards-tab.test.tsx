import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { noteLook } from './dashboards/DashboardView'
import { DashboardsEntry } from './pages/Dashboards'
import { GENERAL_US, mockApi } from './test-utils'

beforeEach(() => localStorage.clear())
afterEach(() => vi.unstubAllGlobals())

const summaries = [
  { id: 1, name: 'Overview', is_default: true, sort_order: 1, widget_count: 2 },
  { id: 3, name: 'Risk', is_default: false, sort_order: 2, widget_count: 4 },
]

function visit() {
  mockApi({
    '/api/v1/settings/general': GENERAL_US,
    'GET /api/v1/dashboards': summaries,
    '/api/v1/dashboard-templates': [],
  })
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={['/dashboards']}>
        <Routes>
          <Route path="/dashboards" element={<DashboardsEntry />} />
          <Route path="/dashboards/:id" element={<p>the dashboard page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('the Dashboards tab', () => {
  it('shows the list of dashboards until one is chosen for the tab', async () => {
    visit()
    expect(await screen.findByRole('heading', { name: 'Dashboards' })).toBeVisible()
    expect(screen.queryByText('the dashboard page')).toBeNull()
  })

  it('opens the dashboard that was chosen for it', async () => {
    localStorage.setItem('folio.dashboards.tab', '3')
    visit()
    expect(await screen.findByText('the dashboard page')).toBeVisible()
  })

  it('shows the list again when the chosen dashboard no longer exists', async () => {
    localStorage.setItem('folio.dashboards.tab', '99')
    visit()
    expect(await screen.findByRole('heading', { name: 'Dashboards' })).toBeVisible()
    expect(screen.queryByText('the dashboard page')).toBeNull()
  })
})

describe('how a note looks', () => {
  const note = (config: Record<string, unknown>) => ({ type: 'note', config })

  it('is the plain small title unless it is changed', () => {
    const look = noteLook(note({}))
    expect(look.titleOnly).toBe(false)
    expect(look.style).toBeUndefined()
    expect(look.titleClass).toContain('text-sm')
  })

  it('takes the chosen title size, tint and title-only switch', () => {
    const look = noteLook(note({ title_only: true, title_size: 'xlarge', background: 'amber' }))
    expect(look.titleOnly).toBe(true)
    expect(look.titleClass).toContain('text-4xl')
    expect(look.style?.background).toContain('color-mix')
    expect(look.style?.background).toContain('var(--card)')
  })

  it('leaves every other widget as it was', () => {
    const look = noteLook({
      type: 'kpi',
      config: { title_only: true, title_size: 'xlarge', background: 'red' },
    })
    expect(look.titleOnly).toBe(false)
    expect(look.style).toBeUndefined()
    expect(look.titleClass).toContain('text-sm')
  })
})
