import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ProvidersTab } from './system/ProvidersTab'
import { GENERAL_US, mockApi, renderAt } from './test-utils'

afterEach(() => vi.unstubAllGlobals())

const usage = (provider: string, over: Record<string, unknown> = {}) => ({
  provider,
  calls_today: 3,
  daily_budget: null,
  remaining: null,
  enabled: true,
  has_key: null,
  ...over,
})
const config = (enabled = true) => ({ enabled, priority: 1, daily_call_budget: 0 })

describe('providers (FR-SY-09)', () => {
  it('lists each source with what it is for, its calls today, and whether it lacks a key', async () => {
    mockApi({
      '/api/v1/settings/general': GENERAL_US,
      '/api/v1/system/usage': [
        usage('eodhd', { has_key: false, daily_budget: 20, calls_today: 4 }),
        usage('yahoo'),
        usage('fred', { enabled: false, has_key: true }),
      ],
      '/api/v1/settings/providers': {
        providers: { eodhd: config(), yahoo: config(), fred: config(false) },
        eodhd_api_key: null,
        twelvedata_api_key: null,
        openfigi_api_key: null,
        fred_api_key: null,
      },
    })
    renderAt(<ProvidersTab />)
    const eodhd = (await screen.findByText('EODHD')).closest('li') as HTMLElement
    expect(within(eodhd).getByText('No key saved')).toBeInTheDocument()
    expect(within(eodhd).getByText('Calls today: 4 of 20')).toBeInTheDocument()
    expect(within(eodhd).getByText(/free plan allows 20 calls a day/)).toBeInTheDocument()
    const fred = screen.getByText('FRED').closest('li') as HTMLElement
    expect(within(fred).getByText('Off')).toBeInTheDocument()
    expect(within(fred).getByLabelText('FRED is on')).not.toBeChecked()
  })

  it('switches one source off without touching the others', async () => {
    const { calls } = mockApi({
      '/api/v1/settings/general': GENERAL_US,
      '/api/v1/system/usage': [usage('yahoo'), usage('ecb')],
      'GET /api/v1/settings/providers': {
        providers: { yahoo: config(), ecb: config() },
        eodhd_api_key: null,
        twelvedata_api_key: null,
        openfigi_api_key: null,
        fred_api_key: null,
      },
      'PUT /api/v1/settings/providers': {},
    })
    renderAt(<ProvidersTab />)
    await userEvent.click(await screen.findByLabelText('Yahoo Finance is on'))
    await waitFor(() => expect(calls.some((c) => c.method === 'PUT')).toBe(true))
    expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({
      providers: { yahoo: { ...config(), enabled: false }, ecb: config() },
    })
  })
})
