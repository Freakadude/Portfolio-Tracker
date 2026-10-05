import { expect, test } from '@playwright/test'
import { euro, login } from './helpers'

// FR-TX-12, FR-TX-10, FR-TX-11, on what the earlier files left behind: E2E Stock (ISIN
// US0378331005) bought 10 + 5 and sold 12 in 2025 (realized result 318,60), 3 units left, and
// E2E Watched, a hand-priced instrument nobody holds.

test('the report for 2025 shows the sale and downloads as CSV (FR-TX-12)', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: 'Reports' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Reports' })).toBeVisible()
  await page.getByLabel('Year').selectOption('2025')

  const sales = page.getByRole('table', { name: 'Sales' })
  const row = sales.getByRole('row', { name: /E2E Stock/ })
  await expect(row).toContainText(euro('1\\.560,00')) // proceeds
  await expect(row).toContainText(euro('1\\.241,40')) // cost basis of the two lots used
  await expect(row).toContainText(euro('318,60'))
  await expect(page.getByText('Realized result').locator('..')).toContainText(euro('318,60'))

  const download = page.waitForEvent('download')
  await page.getByRole('link', { name: 'Download CSV' }).click()
  expect((await download).suggestedFilename()).toBe('folio-realized-2025.csv')
})

test('reconcile lists what differs from the broker and changes nothing (FR-TX-10)', async ({
  page,
}) => {
  await login(page)
  await page.getByRole('link', { name: 'Transactions' }).click()
  await page.getByRole('button', { name: 'Reconcile' }).click()
  const dialog = page.getByRole('dialog', { name: 'Reconcile with your broker' })
  await dialog.getByLabel('Holdings from your broker').fill('US0378331005\t4\nIE00B5BMR087\t2')
  await dialog.getByRole('button', { name: 'Compare' }).click()

  await expect(dialog.getByRole('status')).toContainText('2 lines differ')
  const table = dialog.getByRole('table', { name: 'Result of the comparison' })
  const ours = table.getByRole('row', { name: /E2E Stock/ })
  await expect(ours).toContainText('Differs')
  await expect(ours).toContainText('3') // in Folio
  await expect(ours).toContainText('4') // at the broker
  await expect(table.getByRole('row', { name: /IE00B5BMR087/ })).toContainText('Not in Folio')
  await ours.getByRole('link', { name: 'Show transactions' }).click()
  await expect(page).toHaveURL(/\/transactions\?instrument=\d+/)
})

test('quick add saves several buys together, or none (FR-TX-11)', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: 'Transactions' }).click()
  await page.getByRole('button', { name: 'Quick add' }).click()
  const dialog = page.getByRole('dialog', { name: 'Quick add' })

  // an incomplete or fractional row is named and nothing is sent
  const first = dialog.getByRole('group', { name: 'Buy 1' })
  await first.getByLabel('Instrument').selectOption('E2E Stock')
  await first.getByLabel('Units').fill('1.5')
  await dialog.getByRole('button', { name: 'Save all' }).click()
  await expect(dialog.getByRole('alert')).toContainText('Row 1: enter whole units, at least 1.')

  // the amount is split by share into whole units: 500 x 60% / 150 = 2, 500 x 40% / 20 = 10
  await dialog.getByLabel('Amount to spend (EUR)').fill('500')
  await first.getByLabel('Price').fill('150')
  await first.getByLabel('Share (%)').fill('60')
  const second = dialog.getByRole('group', { name: 'Buy 2' })
  await second.getByLabel('Instrument').selectOption('E2E Watched')
  await second.getByLabel('Price').fill('20')
  await second.getByLabel('Share (%)').fill('40')
  await dialog.getByRole('button', { name: 'Split the amount' }).click()
  await expect(first.getByLabel('Units')).toHaveValue('2')
  await expect(second.getByLabel('Units')).toHaveValue('10')

  await dialog.getByRole('button', { name: 'Save all' }).click()
  await expect(dialog).toBeHidden()
  await expect(page.getByRole('row', { name: /Buy.*E2E Watched/ })).toBeVisible()

  // both holdings are there now: 3 + 2 units, and 10 units that were not held before
  await page.getByRole('link', { name: 'Holdings', exact: true }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Holdings' })).toBeVisible()
  await expect(page.getByRole('row', { name: /E2E Stock/ })).toContainText('5')
  await expect(page.getByRole('row', { name: /E2E Watched/ })).toContainText('10')
})
