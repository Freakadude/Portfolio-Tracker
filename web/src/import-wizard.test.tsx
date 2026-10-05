import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ImportWizard } from './pages/ImportWizard'
import { GENERAL_US, mockApi, problem, renderAt } from './test-utils'

afterEach(() => vi.unstubAllGlobals())

const MAPPING = {
  date_format: '%d-%m-%Y',
  decimal_separator: ',',
  thousands_separator: '',
  date_col: 0,
  isin_col: 1,
  quantity_col: 2,
  price_col: 3,
  type_mode: 'sign',
  type_map: {},
  skip_types: [],
  fx_semantics: 'per_eur',
}
const BATCH = {
  id: 5,
  account_id: 1,
  file_name: 'export.csv',
  status: 'preview',
  rows_total: 2,
  rows_imported: 0,
  rows_skipped: 0,
  preset_id: null,
  created_at: '2025-03-03T10:00:00Z',
  committed_at: null,
  errors: [],
}
const PREVIEW = {
  batch: BATCH,
  encoding: 'utf-8',
  delimiter: ';',
  headers: [
    { index: 0, label: 'Datum' },
    { index: 1, label: 'ISIN' },
    { index: 2, label: 'Aantal' },
    { index: 3, label: 'Koers' },
  ],
  sample_rows: [['03-03-2025', 'US0000000001', '10', '20,50']],
  row_count: 2,
  mapping: MAPPING,
  from_preset: false,
}
const DRY = {
  batch_id: 5,
  counts: { new: 1, duplicate: 0, error: 1, skipped: 0 },
  unknown_isins: [],
  truncated: false,
  can_commit: false,
  rows: [
    {
      row: 2,
      status: 'new',
      reason: null,
      summary: {
        date: '2025-03-03',
        type: 'buy',
        isin: 'US0000000001',
        quantity: '10',
        price: '20.50',
      },
    },
    { row: 3, status: 'error', reason: 'Cannot read "abc" as a date.', summary: null },
  ],
}

const ROUTES = {
  '/api/v1/settings/general': GENERAL_US,
  '/api/v1/accounts': [
    {
      id: 1,
      name: 'Degiro',
      broker: null,
      cost_basis_method: 'FIFO',
      base_currency: 'EUR',
      active: true,
      transaction_count: 0,
    },
  ],
  '/api/v1/import-presets': [],
  'GET /api/v1/imports': [],
}

async function uploadFile() {
  const file = new File(['Datum;ISIN\n'], 'export.csv', { type: 'text/csv' })
  await userEvent.upload(await screen.findByLabelText('CSV file'), file)
  await userEvent.click(screen.getByRole('button', { name: 'Upload and continue' }))
}

describe('the import wizard', () => {
  it('asks for a file before uploading anything', async () => {
    const { calls } = mockApi(ROUTES)
    renderAt(<ImportWizard />)
    await userEvent.click(await screen.findByRole('button', { name: 'Upload and continue' }))
    expect(await screen.findByText('Choose a file first.')).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
  })

  it('walks from the file to the review and imports the valid rows only', async () => {
    const { calls } = mockApi({
      ...ROUTES,
      'POST /api/v1/imports': PREVIEW,
      'PUT /api/v1/imports/5/mapping': DRY,
      'POST /api/v1/imports/5/commit': {
        ...BATCH,
        status: 'committed',
        rows_imported: 1,
        rows_skipped: 1,
      },
    })
    renderAt(<ImportWizard />)
    await uploadFile()

    // columns: the first guess is filled in from the server
    expect(await screen.findByText(/2 rows found/)).toBeInTheDocument()
    expect(screen.getByLabelText('ISIN', { selector: 'select' })).toHaveValue('1')
    await userEvent.click(screen.getByRole('button', { name: 'Check the file' }))

    // review: one row is fine, one has a problem, and the commit is blocked until the owner chooses
    expect(
      await screen.findByText(/1 new · 0 already imported · 1 with problems/),
    ).toBeInTheDocument()
    expect(screen.getByText('Cannot read "abc" as a date.')).toBeInTheDocument()
    const commit = screen.getByRole('button', { name: 'Import 1 rows' })
    expect(commit).toBeDisabled()
    await userEvent.click(screen.getByLabelText(/Import the valid rows only/))
    expect(commit).toBeEnabled()
    await userEvent.click(commit)

    expect(await screen.findByText(/Imported 1 rows\. 1 rows were left out\./)).toBeInTheDocument()
    const post = calls.find((c) => c.path === '/api/v1/imports/5/commit')
    expect(post?.body).toEqual({ skip_errors: true })
    const put = calls.find((c) => c.method === 'PUT')
    expect(put?.body).toMatchObject({ mapping: { isin_col: 1, decimal_separator: ',' } })
  })

  it('shows the server explanation when the file cannot be read', async () => {
    mockApi({
      ...ROUTES,
      'POST /api/v1/imports': problem(422, 'Import problem', 'The file has no header row.'),
    })
    renderAt(<ImportWizard />)
    await uploadFile()
    expect(await screen.findByText('The file has no header row.')).toBeInTheDocument()
  })

  it('lists past imports and undoes one after confirmation', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const { calls } = mockApi({
      ...ROUTES,
      'GET /api/v1/imports': [
        { ...BATCH, id: 3, status: 'committed', rows_imported: 4, rows_skipped: 0 },
      ],
      'DELETE /api/v1/imports/3': new Response(null, { status: 204 }),
    })
    renderAt(<ImportWizard />)
    expect(await screen.findByText('4 imported · 0 left out')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Undo' }))
    await waitFor(() =>
      expect(calls.some((c) => c.method === 'DELETE' && c.path === '/api/v1/imports/3')).toBe(true),
    )
  })

  it('says which broker it recognised and lets the owner add a fee column', async () => {
    const { calls } = mockApi({
      ...ROUTES,
      'POST /api/v1/imports': { ...PREVIEW, detected_preset: 'degiro' },
      'PUT /api/v1/imports/5/mapping': DRY,
    })
    renderAt(<ImportWizard />)
    await uploadFile()
    expect(
      await screen.findByText(/Recognised as a Degiro transactions export/),
    ).toBeInTheDocument()
    await userEvent.click(screen.getByRole('checkbox', { name: 'Koers' }))
    await userEvent.click(screen.getByRole('button', { name: 'Check the file' }))
    await screen.findByText(/1 new/)
    const put = calls.find((c) => c.method === 'PUT')
    expect(put?.body).toMatchObject({ mapping: { extra_fee_cols: [3] } })
  })
})
