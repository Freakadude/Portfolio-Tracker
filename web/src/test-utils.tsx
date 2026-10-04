import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { ReactElement } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { vi } from 'vitest'

type Handler = unknown | ((request: Request) => unknown)

/** Stub the network: keys are "GET /api/v1/positions" or just a path; values are JSON bodies or
 * functions returning one (return a Response for full control). Unknown requests are a 404. */
export function mockApi(routes: Record<string, Handler>) {
  const calls: { method: string; path: string; body: unknown }[] = []
  const fetchMock = vi.fn(async (input: Request | string | URL) => {
    const request = input instanceof Request ? input : new Request(String(input))
    const path = new URL(request.url).pathname
    const method = request.method
    let body: unknown = null
    if (method !== 'GET') {
      const text = await request.clone().text()
      try {
        body = text ? JSON.parse(text) : null
      } catch {
        body = text
      }
    }
    calls.push({ method, path, body })
    const handler = routes[`${method} ${path}`] ?? routes[path]
    if (handler === undefined) return new Response(null, { status: 404 })
    const value = typeof handler === 'function' ? await handler(request) : handler
    return value instanceof Response ? value : Response.json(value)
  })
  vi.stubGlobal('fetch', fetchMock)
  return { fetchMock, calls }
}

export function problem(status: number, title: string, detail: string, extra: object = {}) {
  return new Response(JSON.stringify({ title, detail, status, ...extra }), {
    status,
    headers: { 'content-type': 'application/problem+json' },
  })
}

export const GENERAL_US = { timezone: 'Europe/Amsterdam', number_format: 'us' }

/** Render a page with the providers the app has, at a route. */
export function renderAt(ui: ReactElement, path = '/', routePath = '*') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path={routePath} element={ui} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}
