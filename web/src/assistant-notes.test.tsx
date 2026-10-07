import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { StrategyHelper } from './assistant/StrategyHelper'
import { GENERAL_US, mockApi, renderAt } from './test-utils'

afterEach(() => vi.unstubAllGlobals())

const note = (over: Record<string, unknown> = {}) => ({
  id: 1,
  title: 'Goals',
  body: 'Retire at 60.',
  source: 'written',
  use_in_helper: true,
  characters: 13,
  created_at: '2026-10-07T10:00:00Z',
  updated_at: '2026-10-07T10:00:00Z',
  ...over,
})
const list = (notes: unknown[], over: Record<string, unknown> = {}) => ({
  notes,
  note_limit: 6000,
  total_limit: 12000,
  used: 13,
  left_out: 0,
  ...over,
})

describe('the strategy helper background notes (ADR 0048)', () => {
  it('lists the notes, what the helper reads, and says when some do not fit', async () => {
    mockApi({
      '/api/v1/settings/general': GENERAL_US,
      '/api/v1/assistant/notes': list([note(), note({ id: 2, title: 'Views', source: 'pasted' })], {
        left_out: 1,
      }),
      '/api/v1/assistant/notes/request': { text: 'Please write my profile' },
    })
    renderAt(<StrategyHelper />)
    expect(await screen.findByText('Goals')).toBeInTheDocument()
    expect(screen.getByText('From Claude')).toBeInTheDocument()
    expect(screen.getByText(/reads 13 of at most 12,000 characters/)).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('1 switched-on note(s) do not fit')
  })

  it('writes a note and sends it as written by hand', async () => {
    const { calls } = mockApi({
      '/api/v1/settings/general': GENERAL_US,
      'GET /api/v1/assistant/notes': list([]),
      'POST /api/v1/assistant/notes': note({ id: 5, title: 'Horizon' }),
      '/api/v1/assistant/notes/request': { text: 'x' },
    })
    renderAt(<StrategyHelper />)
    expect(await screen.findByText(/No notes yet/)).toBeInTheDocument()
    const user = userEvent.setup()
    const form = screen.getByRole('form', { name: 'Write a note' })
    await user.type(within(form).getByLabelText('Title'), 'Horizon')
    await user.type(within(form).getByLabelText('Note'), 'Twenty years.')
    await user.click(within(form).getByRole('button', { name: 'Add note' }))
    await vi.waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    expect(calls.find((c) => c.method === 'POST')?.body).toMatchObject({
      title: 'Horizon',
      body: 'Twenty years.',
      source: 'written',
    })
  })

  it('shows the text to ask Claude for a profile and saves what comes back as a note from Claude', async () => {
    const { calls } = mockApi({
      '/api/v1/settings/general': GENERAL_US,
      'GET /api/v1/assistant/notes': list([]),
      'POST /api/v1/assistant/notes': note({ id: 6, source: 'pasted' }),
      '/api/v1/assistant/notes/request': { text: 'Please write my profile' },
    })
    renderAt(<StrategyHelper />)
    const user = userEvent.setup()
    await user.click(await screen.findByRole('tab', { name: /Ask Claude to write it/ }))
    expect(await screen.findByDisplayValue('Please write my profile')).toHaveAttribute('readonly')
    const form = screen.getByRole('form', { name: 'Save what Claude wrote' })
    await user.type(within(form).getByLabelText('What Claude wrote'), 'I invest for the long run.')
    await user.click(within(form).getByRole('button', { name: 'Save as note' }))
    await vi.waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    expect(calls.find((c) => c.method === 'POST')?.body).toMatchObject({
      title: 'My investing profile',
      body: 'I invest for the long run.',
      source: 'pasted',
    })
  })

  it('switches a note off for the helper', async () => {
    const { calls } = mockApi({
      '/api/v1/settings/general': GENERAL_US,
      'GET /api/v1/assistant/notes': list([note()]),
      'PATCH /api/v1/assistant/notes/1': note({ use_in_helper: false }),
      '/api/v1/assistant/notes/request': { text: 'x' },
    })
    renderAt(<StrategyHelper />)
    const user = userEvent.setup()
    await user.click(await screen.findByLabelText('Use in helper'))
    await vi.waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true))
    expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ use_in_helper: false })
  })
})
