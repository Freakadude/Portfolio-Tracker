import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { Login } from './pages/Login'
import { SecurityTab } from './security/SecurityTab'
import { GENERAL_US, mockApi, problem, renderAt } from './test-utils'

beforeEach(() => {
  document.cookie = 'folio_csrf=abc123'
})
afterEach(() => vi.unstubAllGlobals())

const SIGNED_OUT = {
  needs_owner: false,
  authenticated: false,
  has_account: true,
  setup_complete: true,
}

describe('signing in with a second factor (FR-SY-03)', () => {
  it('asks for the code after the password, then signs in with it', async () => {
    const seen: unknown[] = []
    mockApi({
      '/api/v1/setup/status': SIGNED_OUT,
      'POST /api/v1/auth/login': async (request: Request) => {
        const body = (await request.clone().json()) as { code?: string | null }
        seen.push(body.code ?? null)
        if (!body.code)
          return problem(401, 'Code needed', 'Enter the code.', { code: 'totp_required' })
        return { username: 'owner' }
      },
    })
    renderAt(<Login />, '/login')
    await userEvent.type(await screen.findByLabelText('Username'), 'owner')
    await userEvent.type(screen.getByLabelText('Password'), 'secret secret secret')
    expect(screen.queryByLabelText(/Code from your authenticator app/)).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    const code = await screen.findByLabelText(
      'Code from your authenticator app, or a recovery code',
    )
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Enter the code from your authenticator app',
    )
    expect(screen.getByLabelText('Password')).toHaveValue('secret secret secret') // kept
    await userEvent.type(code, '123456')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    await waitFor(() => expect(seen).toEqual([null, '123456']))
  })

  it('says so plainly when the code was wrong', async () => {
    mockApi({
      '/api/v1/setup/status': SIGNED_OUT,
      'POST /api/v1/auth/login': () =>
        problem(401, 'Wrong code', 'That code is not right or was already used.', {
          code: 'totp_required',
        }),
    })
    renderApp()
    await userEvent.type(await screen.findByLabelText('Username'), 'owner')
    await userEvent.type(screen.getByLabelText('Password'), 'secret secret secret')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'That code is not right or was already used.',
    )
  })

  function renderApp() {
    return renderAt(<Login />, '/login')
  }
})

const OFF = { enabled: false, pending: false, recovery_codes_left: 0 }
const ON = { enabled: true, pending: false, recovery_codes_left: 10 }
const CODES = ['AAAA-BBBB-CCCC', 'DDDD-EEEE-FFFF']

describe('the Security tab', () => {
  it('sets it up: QR code and key, a code from the app, then the recovery codes once', async () => {
    let enabled = false
    const { calls } = mockApi({
      '/api/v1/settings/general': GENERAL_US,
      '/api/v1/auth/totp': () => (enabled ? ON : OFF),
      'POST /api/v1/auth/totp/setup': {
        secret: 'ABCD EFGH IJKL MNOP QRST UVWX YZ23 4567',
        uri: 'otpauth://totp/Folio%3Aowner?secret=X',
        qr_svg: '<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>',
      },
      'POST /api/v1/auth/totp/enable': () => {
        enabled = true
        return { recovery_codes: CODES }
      },
    })
    renderAt(<SecurityTab />)
    expect(await screen.findByText('Off.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Set up two-factor sign-in' }))
    expect(await screen.findByAltText('QR code for your authenticator app')).toHaveAttribute(
      'src',
      expect.stringContaining('data:image/svg+xml'),
    )
    expect(screen.getByText('ABCD EFGH IJKL MNOP QRST UVWX YZ23 4567')).toBeInTheDocument()
    const turnOn = screen.getByRole('button', { name: 'Turn on' })
    expect(turnOn).toBeDisabled() // no code yet
    await userEvent.type(screen.getByLabelText('The six-digit code the app now shows'), '654321')
    await userEvent.click(turnOn)
    const codes = await screen.findByRole('list', { name: 'Your recovery codes' })
    expect(
      within(codes)
        .getAllByRole('listitem')
        .map((li) => li.textContent),
    ).toEqual(CODES)
    expect(calls.find((c) => c.path === '/api/v1/auth/totp/enable')?.body).toEqual({
      code: '654321',
    })
    expect(screen.getByRole('link', { name: 'Download as a text file' })).toHaveAttribute(
      'download',
      'folio-recovery-codes.txt',
    )
    const done = screen.getByRole('button', { name: 'Done' })
    expect(done).toBeDisabled() // until you say you saved them
    await userEvent.click(screen.getByLabelText('I have saved these codes'))
    await userEvent.click(done)
    expect(await screen.findByText('On. 10 recovery code(s) left.')).toBeInTheDocument()
    expect(screen.queryByText('AAAA-BBBB-CCCC')).not.toBeInTheDocument() // shown only once
  })

  it('shows a refused code in words', async () => {
    mockApi({
      '/api/v1/auth/totp': OFF,
      'POST /api/v1/auth/totp/setup': { secret: 'ABCD', uri: 'otpauth://x', qr_svg: '<svg/>' },
      'POST /api/v1/auth/totp/enable': () =>
        problem(422, 'Cannot turn it on', 'That code is not right. Check the clock of your phone.'),
    })
    renderAt(<SecurityTab />)
    await userEvent.click(await screen.findByRole('button', { name: 'Set up two-factor sign-in' }))
    await userEvent.type(
      await screen.findByLabelText('The six-digit code the app now shows'),
      '000000',
    )
    await userEvent.click(screen.getByRole('button', { name: 'Turn on' }))
    expect(await screen.findByText(/Check the clock of your phone/)).toBeInTheDocument()
  })

  it('turns it off only with the password and a code, and makes new recovery codes', async () => {
    let enabled = true
    const { calls } = mockApi({
      '/api/v1/auth/totp': () => (enabled ? ON : OFF),
      'POST /api/v1/auth/totp/disable': () => {
        enabled = false
        return new Response(null, { status: 204 })
      },
      'POST /api/v1/auth/totp/recovery-codes': { recovery_codes: CODES },
    })
    renderAt(<SecurityTab />)
    expect(await screen.findByText('On. 10 recovery code(s) left.')).toBeInTheDocument()
    const off = screen.getByRole('button', { name: 'Turn off' })
    const renew = screen.getByRole('button', { name: 'Make new recovery codes' })
    expect(off).toBeDisabled()
    expect(renew).toBeDisabled()
    await userEvent.type(screen.getByLabelText('Password'), 'secret secret secret')
    await userEvent.type(screen.getByLabelText('A code from the app, or a recovery code'), '123456')
    await userEvent.click(renew)
    expect(await screen.findByRole('list', { name: 'Your recovery codes' })).toBeInTheDocument()
    expect(calls.find((c) => c.path === '/api/v1/auth/totp/recovery-codes')?.body).toEqual({
      password: 'secret secret secret',
      code: '123456',
    })
    await userEvent.click(screen.getByLabelText('I have saved these codes'))
    await userEvent.click(screen.getByRole('button', { name: 'Done' }))
    await userEvent.type(await screen.findByLabelText('Password'), 'secret secret secret')
    await userEvent.type(screen.getByLabelText('A code from the app, or a recovery code'), '654321')
    await userEvent.click(screen.getByRole('button', { name: 'Turn off' }))
    expect(await screen.findByText('Off.')).toBeInTheDocument()
    expect(calls.some((c) => c.path === '/api/v1/auth/totp/disable')).toBe(true)
  })
})

describe('signing in through Tailscale (FR-SY-04)', () => {
  it('offers the button only when the request comes through Tailscale Serve, and signs in', async () => {
    const { calls } = mockApi({
      '/api/v1/setup/status': SIGNED_OUT,
      '/api/v1/auth/methods': { tailscale: true },
      'POST /api/v1/auth/tailscale': { username: 'owner' },
    })
    renderAt(<Login />, '/login')
    await userEvent.click(await screen.findByRole('button', { name: 'Sign in through Tailscale' }))
    await waitFor(() =>
      expect(calls.some((c) => c.method === 'POST' && c.path === '/api/v1/auth/tailscale')).toBe(
        true,
      ),
    )
  })

  it('shows no button otherwise', async () => {
    mockApi({ '/api/v1/setup/status': SIGNED_OUT, '/api/v1/auth/methods': { tailscale: false } })
    renderAt(<Login />, '/login')
    await screen.findByLabelText('Username')
    expect(
      screen.queryByRole('button', { name: 'Sign in through Tailscale' }),
    ).not.toBeInTheDocument()
  })

  it('says so when the sign-in is refused', async () => {
    mockApi({
      '/api/v1/setup/status': SIGNED_OUT,
      '/api/v1/auth/methods': { tailscale: true },
      'POST /api/v1/auth/tailscale': () =>
        problem(401, 'Not available', 'Signing in through Tailscale is not available here.'),
    })
    renderAt(<Login />, '/login')
    await userEvent.click(await screen.findByRole('button', { name: 'Sign in through Tailscale' }))
    expect(await screen.findByText(/not available here/)).toBeInTheDocument()
  })
})
