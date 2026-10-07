import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PasteMode } from './assistant/PasteMode'
import { GENERAL_US, mockApi, renderAt } from './test-utils'

afterEach(() => vi.unstubAllGlobals())

const YAML = 'strategy:\n  name: "Mine"\n  sleeves: []\n'
const ANSWER = `Here is your strategy:\n\n\`\`\`yaml\n${YAML}\`\`\`\n\nIt warns you when ...`
const DEFINITION = {
  strategy: {
    name: 'Mine',
    sleeves: [{ id: 'Core', members: [], target_pct: '70', soft_band_pp: '3', hard_band_pp: '6' }],
    rules: [{ id: 'd', type: 'drift_band' }],
  },
}
const summary = (over: Record<string, unknown> = {}) => ({
  id: 1,
  name: 'Old plan',
  mode: 'off',
  version: 1,
  updated_at: '2026-10-01T10:00:00Z',
  ...over,
})
const saved = { id: 7, name: 'Mine', mode: 'off', current: {}, versions: [] }
const base = (more: Record<string, unknown> = {}) => ({
  '/api/v1/settings/general': GENERAL_US,
  'GET /api/v1/strategies': [summary()],
  '/api/v1/assistant/prompt': { text: 'You help an investor ...', characters: 24, notes_used: 120 },
  ...more,
})

describe('the strategy helper on the Claude subscription (ADR 0048)', () => {
  it('gives a prompt to copy, checks the answer pasted back and saves it switched off', async () => {
    const { calls } = mockApi(
      base({
        'POST /api/v1/strategies/check': {
          ok: true,
          problems: [],
          yaml: YAML,
          definition: DEFINITION,
        },
        'POST /api/v1/strategies': saved,
      }),
    )
    renderAt(<PasteMode />)
    const user = userEvent.setup()
    expect(await screen.findByLabelText('Prompt for Claude')).toHaveValue(
      'You help an investor ...',
    )
    expect(screen.getByText(/120 characters of your background notes/)).toBeVisible()

    await user.type(screen.getByLabelText(/Claude's answer/), 'x')
    await user.clear(screen.getByLabelText(/Claude's answer/))
    await user.click(screen.getByLabelText(/Claude's answer/))
    await user.paste(ANSWER)
    await user.click(screen.getByRole('button', { name: 'Check it' }))
    // only the strategy document goes to the check, not the chat around it
    await vi.waitFor(() => expect(calls.some((c) => c.path.endsWith('/check'))).toBe(true))
    expect(calls.find((c) => c.path.endsWith('/check'))?.body).toEqual({ yaml: YAML.trim() })

    expect(await screen.findByText(/Core: target 70% of the portfolio/)).toBeVisible()
    expect(
      screen.getByText(/early warning at 3 points off target, firm warning at 6/),
    ).toBeVisible()
    expect(screen.getByText('Warn when a group drifts outside its band.')).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Save as a new strategy (switched off)' }))
    await vi.waitFor(() =>
      expect(calls.some((c) => c.method === 'POST' && c.path === '/api/v1/strategies')).toBe(true),
    )
    expect(
      calls.find((c) => c.method === 'POST' && c.path === '/api/v1/strategies')?.body,
    ).toMatchObject({ yaml: YAML, note: 'strategy helper' })
  })

  it('shows the problems with their lines and lets them be copied back to Claude', async () => {
    mockApi(
      base({
        'POST /api/v1/strategies/check': {
          ok: false,
          problems: [{ line: 3, path: 'sleeves.0', message: 'targets must add up to 100' }],
          yaml: null,
          definition: null,
        },
      }),
    )
    renderAt(<PasteMode />)
    const user = userEvent.setup()
    await user.click(await screen.findByLabelText(/Claude's answer/))
    await user.paste(ANSWER)
    await user.click(screen.getByRole('button', { name: 'Check it' }))
    const box = await screen.findByRole('alert')
    expect(box).toHaveTextContent('line 3: targets must add up to 100')
    expect(screen.getByRole('button', { name: 'Copy the problems for Claude' })).toBeVisible()
    expect(screen.queryByRole('button', { name: /Save as/ })).toBeNull()
  })

  it('to revise, asks for the prompt of that strategy, shows what changes and warns when it is active', async () => {
    const { calls, fetchMock } = mockApi(
      base({
        'GET /api/v1/strategies': [summary({ mode: 'active' })],
        'POST /api/v1/strategies/check': {
          ok: true,
          problems: [],
          yaml: YAML,
          definition: DEFINITION,
        },
        'POST /api/v1/assistant/diff': {
          changed: true,
          rows: [
            {
              kind: 'same',
              old_line: 1,
              old_text: 'strategy:',
              new_line: 1,
              new_text: 'strategy:',
            },
            {
              kind: 'changed',
              old_line: 2,
              old_text: 'threshold_pct: 20',
              new_line: 2,
              new_text: 'threshold_pct: 25',
            },
          ],
        },
        'POST /api/v1/strategies/1/versions': saved,
      }),
    )
    renderAt(<PasteMode />)
    const user = userEvent.setup()
    await user.click(await screen.findByLabelText('Revise a strategy I have'))
    await user.selectOptions(screen.getByLabelText('Strategy to revise'), '1')
    await vi.waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([r]) => {
          const url = String((r as Request).url)
          return (
            url.includes('/assistant/prompt') &&
            url.includes('mode=revise') &&
            url.includes('strategy=1')
          )
        }),
      ).toBe(true),
    )
    await user.click(screen.getByLabelText(/Claude's answer/))
    await user.paste(ANSWER)
    await user.click(screen.getByRole('button', { name: 'Check it' }))
    expect(await screen.findByText('threshold_pct: 25')).toBeVisible()
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Old plan is active, so a new version starts',
    )
    await user.click(screen.getByRole('button', { name: 'Save as a new version of Old plan' }))
    await vi.waitFor(() =>
      expect(calls.some((c) => c.path === '/api/v1/strategies/1/versions')).toBe(true),
    )
  })
})
