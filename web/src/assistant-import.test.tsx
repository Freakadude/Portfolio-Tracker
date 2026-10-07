import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { NotesPanel } from './assistant/NotesPanel'
import { GENERAL_US, mockApi, renderAt } from './test-utils'

afterEach(() => vi.unstubAllGlobals())

const chat = (over: Record<string, unknown> = {}) => ({
  id: 'c-invest',
  title: 'ETF mix for twenty years',
  created_at: '2026-03-01T10:00:00Z',
  messages: 6,
  characters: 1200,
  hits: 4,
  relevant: true,
  opening: 'I want to invest in a world ETF and some bonds.',
  ...over,
})
const NOTES = { notes: [], note_limit: 6000, total_limit: 12000, used: 0, left_out: 0 }
const file = () => new File(['{}'], 'export.zip', { type: 'application/zip' })

async function open() {
  const user = userEvent.setup()
  await user.click(await screen.findByRole('tab', { name: 'From my chat export' }))
  return user
}

describe('importing chats from claude.ai as notes (ADR 0048)', () => {
  it('finds the chats, shows the cost first, and keeps the summary you accept as a note', async () => {
    const { calls } = mockApi({
      '/api/v1/settings/general': GENERAL_US,
      'GET /api/v1/assistant/notes': NOTES,
      '/api/v1/assistant/notes/request': { text: 'x' },
      '/api/v1/assistant/chats/scan': {
        chats: [chat(), chat({ id: 'c-cook', title: 'Pasta', hits: 0, relevant: false })],
        total: 2,
        relevant: 1,
      },
      '/api/v1/assistant/chats/estimate': {
        chats: 1,
        tokens: 900,
        cost_eur: '0.0120',
        remaining_eur: '4.50',
        fits: true,
        model: 'claude-haiku-4-5-20251001',
        max_chats: 8,
      },
      '/api/v1/assistant/chats/summarise': {
        summaries: [
          {
            id: 'c-invest',
            title: 'ETF mix for twenty years',
            text: '- I invest for retirement.',
            cost_eur: '0.0031',
          },
        ],
        failed: [],
        stopped: null,
        cost_eur: '0.0031',
      },
      'POST /api/v1/assistant/notes': {
        id: 9,
        title: 'ETF mix for twenty years',
        body: '- I invest for retirement.',
        source: 'chat_export',
        use_in_helper: true,
        characters: 26,
        created_at: '2026-10-07T10:00:00Z',
        updated_at: '2026-10-07T10:00:00Z',
      },
    })
    renderAt(<NotesPanel />)
    const user = await open()
    await user.upload(screen.getByLabelText('Export file from claude.ai'), file())
    expect(
      await screen.findByText(/2 chats found; 1 look like talks about investing/),
    ).toBeVisible()
    // the chat about investing is ticked for you, the other is not
    expect(screen.getByLabelText('ETF mix for twenty years')).toBeChecked()
    expect(screen.getByLabelText('Pasta')).not.toBeChecked()

    await user.click(screen.getByRole('button', { name: 'Check the cost of 1 chat(s)' }))
    expect(await screen.findByText(/can cost up to/)).toBeVisible()
    expect(screen.getByText(/Nothing is sent before you press the button below/)).toBeVisible()
    expect(calls.some((c) => c.path.endsWith('/summarise'))).toBe(false) // not yet

    await user.click(screen.getByRole('button', { name: 'Summarise 1 chat(s)' }))
    const box = await screen.findByLabelText('Summary of ETF mix for twenty years')
    expect(box).toHaveValue('- I invest for retirement.')
    await user.type(box, ' Edited.')
    await user.click(screen.getByRole('button', { name: 'Save 1 note(s)' }))
    expect(await screen.findByText(/Saved 1 note\(s\)/)).toBeVisible()
    expect(calls.find((c) => c.method === 'POST' && c.path.endsWith('/notes'))?.body).toMatchObject(
      {
        title: 'ETF mix for twenty years',
        body: '- I invest for retirement. Edited.',
        source: 'chat_export',
      },
    )
  })

  it('says when it does not fit the budget and when a file is not an export', async () => {
    mockApi({
      '/api/v1/settings/general': GENERAL_US,
      'GET /api/v1/assistant/notes': NOTES,
      '/api/v1/assistant/notes/request': { text: 'x' },
      '/api/v1/assistant/chats/scan': {
        chats: [chat()],
        total: 1,
        relevant: 1,
      },
      '/api/v1/assistant/chats/estimate': {
        chats: 1,
        tokens: 900,
        cost_eur: '0.0120',
        remaining_eur: '0.0010',
        fits: false,
        model: 'claude-haiku-4-5-20251001',
        max_chats: 8,
      },
    })
    renderAt(<NotesPanel />)
    const user = await open()
    await user.upload(screen.getByLabelText('Export file from claude.ai'), file())
    await user.click(await screen.findByRole('button', { name: 'Check the cost of 1 chat(s)' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/does not fit what is left/)
    expect(screen.getByRole('button', { name: 'Summarise 1 chat(s)' })).toBeDisabled()
  })
})
