import { expect, test } from '@playwright/test'
import { login } from './helpers'

// FR-TX-07: an invented, Dutch-shaped export (semicolons, comma decimals) goes through the wizard,
// importing it twice adds nothing the second time, and undo removes the batch.
const CSV = [
  'Datum;ISIN;Aantal;Koers;Valuta',
  '03-03-2025;US0378331005;2;110,50;EUR',
  '04-03-2025;US0378331005;1;111,25;EUR',
  '',
].join('\n')

async function upload(page: import('@playwright/test').Page) {
  await page.goto('/transactions/import')
  await page.getByLabel('CSV file').setInputFiles({
    name: 'invented-export.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from(CSV, 'utf-8'),
  })
  await page.getByRole('button', { name: 'Upload and continue' }).click()
  await expect(page.getByText(/2 rows found/)).toBeVisible()
  await page.getByRole('button', { name: 'Check the file' }).click()
}

test('import a CSV, import it again (nothing new), then undo the first import', async ({
  page,
}) => {
  await login(page)

  await upload(page)
  await expect(page.getByRole('status')).toContainText(
    '2 new · 0 already imported · 0 with problems',
  )
  await page.getByRole('button', { name: 'Import 2 rows' }).click()
  await expect(page.getByText('Imported 2 rows. 0 rows were left out.')).toBeVisible()

  await page.getByRole('link', { name: 'View transactions' }).click()
  await expect(page.getByRole('row', { name: /2025-03-03.*Buy.*E2E Stock/ })).toBeVisible()
  await expect(page.getByRole('row', { name: /2025-03-04.*Buy.*E2E Stock/ })).toBeVisible()

  // the same file again: every row is recognised, so there is nothing to import
  await upload(page)
  await expect(page.getByRole('status')).toContainText('0 new · 2 already imported')
  await expect(page.getByText('There is nothing new to import.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Import 0 rows' })).toBeDisabled()

  // history: discard the unfinished check, undo the real import
  await page.goto('/transactions/import')
  const history = page.getByRole('table', { name: 'Past imports' })
  await page.getByRole('button', { name: 'Discard' }).click()
  await expect(page.getByText('Not finished')).toHaveCount(0)
  page.once('dialog', (d) => void d.accept())
  await history.getByRole('button', { name: 'Undo' }).click()
  await expect(history.getByText('Undone')).toBeVisible()

  await page.getByRole('link', { name: 'Back to transactions' }).click()
  await expect(page.getByRole('row', { name: /2025-03-0[34].*Buy/ })).toHaveCount(0)
  await expect(page.getByRole('row', { name: /E2E Stock/ })).toHaveCount(3) // the hand-entered trades remain
})
