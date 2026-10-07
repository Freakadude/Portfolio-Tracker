import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Login } from './pages/Login'
import { mockApi, renderAt } from './test-utils'

afterEach(() => vi.unstubAllGlobals())

const STATUS = { needs_owner: false, authenticated: false }

async function fillIn() {
  const user = userEvent.setup()
  await user.type(await screen.findByLabelText('Username'), 'owner')
  await user.type(screen.getByLabelText('Password'), 'a long password here')
  return user
}

describe('sign in (FR-SY-02)', () => {
  it('signs in with "remember this device" ticked and sends that choice', async () => {
    const { calls } = mockApi({
      '/api/v1/setup/status': STATUS,
      '/api/v1/auth/methods': { tailscale: false },
      '/api/v1/auth/login': { username: 'owner' },
    })
    renderAt(<Login />)
    const user = await fillIn()
    await user.click(screen.getByLabelText('Remember this device for 30 days'))
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    await vi.waitFor(() => expect(calls.some((c) => c.path === '/api/v1/auth/login')).toBe(true))
    const login = calls.find((c) => c.path === '/api/v1/auth/login')
    expect(login?.body).toMatchObject({ username: 'owner', remember: true })
  })

  it('signs in without it and sends remember: false', async () => {
    const { calls } = mockApi({
      '/api/v1/setup/status': STATUS,
      '/api/v1/auth/methods': { tailscale: false },
      '/api/v1/auth/login': { username: 'owner' },
    })
    renderAt(<Login />)
    const user = await fillIn()
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    await vi.waitFor(() => expect(calls.some((c) => c.path === '/api/v1/auth/login')).toBe(true))
    expect(calls.find((c) => c.path === '/api/v1/auth/login')?.body).toMatchObject({
      remember: false,
    })
  })
})
