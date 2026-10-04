import createClient, { type Middleware } from 'openapi-fetch'
import type { paths } from './schema'

const SAFE = new Set(['GET', 'HEAD', 'OPTIONS'])

export function csrfToken(): string {
  const match = document.cookie.match(/(?:^|;\s*)folio_csrf=([^;]+)/)
  return match ? decodeURIComponent(match[1]) : ''
}

/** Double-submit CSRF: echo the cookie in a header on every unsafe request. */
export const csrfMiddleware: Middleware = {
  onRequest({ request }) {
    if (!SAFE.has(request.method)) request.headers.set('X-CSRF-Token', csrfToken())
    return request
  },
}

// Resolve fetch per call (not at import time) so tests can stub it.
export const api = createClient<paths>({
  baseUrl: window.location.origin,
  fetch: (request) => globalThis.fetch(request),
})
api.use(csrfMiddleware)

export interface FieldError {
  field: string
  message: string
}

/** An RFC 9457 problem+json response from the API. */
export class ApiProblem extends Error {
  status: number
  title: string
  errors: FieldError[]
  /** Any other fields the API put in the problem, such as the transactions blocking a delete. */
  extra: Record<string, unknown>
  constructor(
    status: number,
    title: string,
    detail?: string,
    errors: FieldError[] = [],
    extra: Record<string, unknown> = {},
  ) {
    super(detail || title)
    this.status = status
    this.title = title
    this.errors = errors
    this.extra = extra
  }
}

type Result<T> = { data?: T; error?: unknown; response: Response }

export async function unwrap<T>(request: Promise<Result<T>>): Promise<T> {
  const { data, error, response } = await request
  if (!response.ok || error !== undefined) {
    const { title, detail, errors, ...extra } = (error ?? {}) as {
      title?: string
      detail?: string
      errors?: FieldError[]
      [key: string]: unknown
    }
    throw new ApiProblem(response.status, title ?? response.statusText, detail, errors, extra)
  }
  return data as T
}

export function errorMessage(err: unknown): string {
  if (err instanceof ApiProblem) {
    return err.errors.length
      ? err.errors.map((e) => `${e.field}: ${e.message}`).join(' · ')
      : err.message
  }
  return err instanceof Error ? err.message : String(err)
}
