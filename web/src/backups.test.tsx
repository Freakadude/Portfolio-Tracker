import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { BackupsPanel } from './system/BackupsPanel'
import { GENERAL_US, mockApi, problem, renderAt } from './test-utils'

afterEach(() => vi.unstubAllGlobals())

const BACKUPS = [
  {
    name: 'folio-20261006-030000.db',
    kind: 'folio',
    size: 2_621_440,
    created_at: '2026-10-06T03:00:00Z',
  },
  {
    name: 'pre-restore-20261005-221500.db',
    kind: 'pre-restore',
    size: 512_000,
    created_at: '2026-10-05T22:15:00Z',
  },
]

const routes = (extra: Record<string, unknown> = {}) => ({
  '/api/v1/settings/general': GENERAL_US,
  '/api/v1/system/backups': BACKUPS,
  '/api/v1/system/restore': { pending: false, last: null },
  ...extra,
})

describe('backups and restore (FR-SY-07)', () => {
  it('lists the backups with their kind and size, and links a download without the keys', async () => {
    mockApi(routes())
    renderAt(<BackupsPanel />)
    const table = await screen.findByRole('table', { name: 'Backups on the server' })
    const row = within(table).getByRole('row', { name: /folio-20261006-030000\.db/ })
    expect(row).toHaveTextContent('backup')
    expect(row).toHaveTextContent('2.5 MB')
    expect(within(table).getByRole('row', { name: /pre-restore-/ })).toHaveTextContent(
      'before a restore',
    )
    expect(
      screen.getByRole('link', { name: 'Download folio-20261006-030000.db without the API keys' }),
    ).toHaveAttribute('href', '/api/v1/system/backups/folio-20261006-030000.db')
    expect(screen.getByText(/leaves out your saved API keys/)).toBeInTheDocument()
  })

  it('makes a backup now, with or without the keys', async () => {
    const { calls } = mockApi(
      routes({
        'POST /api/v1/system/backups': { ...BACKUPS[0], name: 'folio-20261006-100000.db' },
      }),
    )
    renderAt(<BackupsPanel />)
    await userEvent.click(await screen.findByRole('button', { name: 'Back up now' }))
    await userEvent.click(screen.getByLabelText('Include the saved API keys (they stay encrypted)'))
    await userEvent.click(screen.getByRole('button', { name: 'Back up now' }))
    await waitFor(() =>
      expect(
        calls.filter((c) => c.method === 'POST' && c.path === '/api/v1/system/backups'),
      ).toHaveLength(2),
    )
    const bodies = calls.filter((c) => c.method === 'POST').map((c) => c.body)
    expect(bodies).toEqual([{ include_secrets: true }, { include_secrets: false }])
  })

  it('restores only after RESTORE is typed, and says Folio is restarting', async () => {
    const { calls } = mockApi(
      routes({
        'POST /api/v1/system/restore': {
          restarting: true,
          note: 'Folio is restarting with the backup. Sign in again in a minute.',
        },
      }),
    )
    renderAt(<BackupsPanel />)
    await userEvent.click(
      await screen.findByRole('button', { name: 'Restore folio-20261006-030000.db' }),
    )
    const dialog = await screen.findByRole('dialog', { name: 'Restore a backup' })
    expect(within(dialog).getByText(/Everything in Folio is replaced/)).toBeInTheDocument()
    expect(within(dialog).getByText(/kept as a "before a restore" backup/)).toBeInTheDocument()
    const go = within(dialog).getByRole('button', { name: 'Restore and restart' })
    expect(go).toBeDisabled()
    await userEvent.type(within(dialog).getByLabelText('Type RESTORE to confirm'), 'restore')
    expect(go).toBeDisabled() // the word is the word
    await userEvent.clear(within(dialog).getByLabelText('Type RESTORE to confirm'))
    await userEvent.type(within(dialog).getByLabelText('Type RESTORE to confirm'), 'RESTORE')
    await userEvent.click(go)
    expect(await within(dialog).findByRole('status')).toHaveTextContent('Folio is restarting')
    expect(
      calls.find((c) => c.path === '/api/v1/system/restore' && c.method === 'POST')?.body,
    ).toEqual({
      name: 'folio-20261006-030000.db',
      confirm: 'RESTORE',
    })
  })

  it('brings in an uploaded backup and offers to restore it', async () => {
    const { calls } = mockApi(
      routes({
        'POST /api/v1/system/backups/upload': {
          name: 'upload-20261006-110000.db',
          kind: 'upload',
          size: 1000,
          created_at: '2026-10-06T11:00:00Z',
        },
      }),
    )
    renderAt(<BackupsPanel />)
    await screen.findByRole('table', { name: 'Backups on the server' })
    await userEvent.click(screen.getByRole('button', { name: 'Upload' }))
    expect(screen.getByText('Choose a file first.')).toBeInTheDocument()
    const file = new File(['x'], 'mine.db', { type: 'application/octet-stream' })
    await userEvent.upload(screen.getByLabelText('Backup file (.db)'), file)
    await userEvent.click(screen.getByRole('button', { name: 'Upload' }))
    expect(await screen.findByRole('dialog', { name: 'Restore a backup' })).toBeInTheDocument()
    expect(screen.getByText('upload-20261006-110000.db')).toBeInTheDocument()
    expect(calls.some((c) => c.path === '/api/v1/system/backups/upload')).toBe(true)
  })

  it('shows why a file was refused', async () => {
    mockApi(
      routes({
        'POST /api/v1/system/backups/upload': () =>
          problem(422, 'Not a Folio backup', 'That file is not a Folio database.'),
      }),
    )
    renderAt(<BackupsPanel />)
    await screen.findByRole('table', { name: 'Backups on the server' })
    await userEvent.upload(
      screen.getByLabelText('Backup file (.db)'),
      new File(['junk'], 'junk.db'),
    )
    await userEvent.click(screen.getByRole('button', { name: 'Upload' }))
    expect(await screen.findByText('That file is not a Folio database.')).toBeInTheDocument()
  })

  it('deletes one after asking', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const { calls } = mockApi(
      routes({ 'DELETE /api/v1/system/backups/pre-restore-20261005-221500.db': null }),
    )
    renderAt(<BackupsPanel />)
    await userEvent.click(
      await screen.findByRole('button', { name: 'Delete pre-restore-20261005-221500.db' }),
    )
    await waitFor(() => expect(calls.some((c) => c.method === 'DELETE')).toBe(true))
    expect(confirm).toHaveBeenCalled()
    confirm.mockRestore()
  })

  it('tells what the last restore did', async () => {
    mockApi(
      routes({
        '/api/v1/system/restore': {
          pending: false,
          last: {
            at: '2026-10-06T10:00:00Z',
            source: 'folio-20261006-030000.db',
            ok: false,
            safety_copy: null,
            error: 'The file is not a valid backup.',
          },
        },
      }),
    )
    renderAt(<BackupsPanel />)
    expect(
      await screen.findByText(/did not work and changed nothing: The file is not a valid backup/),
    ).toBeInTheDocument()
  })
})
