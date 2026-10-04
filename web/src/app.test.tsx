import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from './App'
import { ApiProblem, csrfMiddleware, errorMessage } from './api/client'

type Status = {
  needs_owner: boolean
  authenticated: boolean
  has_account: boolean
  setup_complete: boolean
}

function mockApi(status: Status, extra: Record<string, () => Response> = {}) {
  const fetchMock = vi.fn(async (input: Request | string | URL) => {
    const request = input instanceof Request ? input : new Request(String(input))
    const path = new URL(request.url).pathname
    if (extra[path]) return extra[path]()
    if (path === '/api/v1/setup/status') return Response.json(status)
    if (path.startsWith('/api/v1/settings/')) return Response.json({ theme: 'system' })
    return new Response(null, { status: 404 })
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function renderApp(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('routing gate', () => {
  it('sends a fresh install to the setup wizard', async () => {
    mockApi({ needs_owner: true, authenticated: false, has_account: false, setup_complete: false })
    renderApp('/')
    expect(await screen.findByRole('heading', { name: 'Set up Folio' })).toBeInTheDocument()
    expect(screen.getByLabelText('Username')).toBeInTheDocument()
  })

  it('sends a signed-out owner to login', async () => {
    mockApi({ needs_owner: false, authenticated: false, has_account: true, setup_complete: true })
    renderApp('/holdings')
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
  })

  it('shows the empty Home with navigation once signed in', async () => {
    mockApi(
      { needs_owner: false, authenticated: true, has_account: true, setup_complete: true },
      { '/api/v1/accounts': () => Response.json([]) },
    )
    renderApp('/')
    expect(
      await screen.findByText('Add your first instrument to start tracking your portfolio.'),
    ).toBeInTheDocument()
    const nav = screen.getByRole('navigation', { name: 'Main navigation' })
    expect(nav).toHaveTextContent('Holdings')
    expect(nav).toHaveTextContent('Settings')
  })
})

describe('login', () => {
  beforeEach(() => {
    document.cookie = 'folio_csrf=abc123'
  })

  it('shows the API error in plain language', async () => {
    mockApi(
      { needs_owner: false, authenticated: false, has_account: true, setup_complete: true },
      {
        '/api/v1/auth/login': () =>
          Response.json(
            {
              title: 'Wrong username or password',
              detail: 'Check your credentials and try again.',
              status: 401,
            },
            { status: 401, headers: { 'content-type': 'application/problem+json' } },
          ),
      },
    )
    renderApp('/login')
    await userEvent.type(await screen.findByLabelText('Username'), 'owner')
    await userEvent.type(screen.getByLabelText('Password'), 'nope')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('Check your credentials and try again.'),
    )
  })
})

describe('api client', () => {
  it('adds the CSRF header to unsafe requests only', () => {
    document.cookie = 'folio_csrf=tok-1'
    const post = new Request('http://x/api', { method: 'POST' })
    const get = new Request('http://x/api', { method: 'GET' })
    const call = (r: Request) =>
      csrfMiddleware.onRequest!({ request: r } as Parameters<
        NonNullable<typeof csrfMiddleware.onRequest>
      >[0])
    call(post)
    call(get)
    expect(post.headers.get('X-CSRF-Token')).toBe('tok-1')
    expect(get.headers.get('X-CSRF-Token')).toBeNull()
  })

  it('formats field errors from problem+json', () => {
    const err = new ApiProblem(422, 'Invalid settings', 'bad', [
      { field: 'timezone', message: 'Unknown timezone' },
    ])
    expect(errorMessage(err)).toBe('timezone: Unknown timezone')
  })
})
