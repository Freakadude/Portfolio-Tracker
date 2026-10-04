import { expect, test } from '@playwright/test'
import { euro, login } from './helpers'

// FR-TX-01, FR-TX-04: record trades by hand and see exactly which lots a sale uses before saving.
// The numbers are worked out by hand: two buys, then a sale that spans both lots (FIFO).
//   buy 10 @ 100 + fee 1   -> lot cost 1.001,00
//   buy  5 @ 120 + fee 1   -> lot cost   601,00
//   sell 12 @ 130          -> proceeds 1.560,00
//     lot 1: 10 units, cost 1.001,00
//     lot 2:  2 units, cost 601,00 * 2/5 = 240,40   -> cost 1.241,40, result 318,60
//     remaining: 3 units, cost basis 360,60
test('add two buys, preview a sale across both lots, save it', async ({ page }) => {
  await login(page)

  // an instrument to trade; its ISIN is a public one, used later by the CSV import test
  await page.getByRole('link', { name: 'Holdings' }).click()
  await page.getByRole('button', { name: 'Add instrument' }).first().click()
  const instrumentDialog = page.getByRole('dialog', { name: 'Add instrument' })
  await instrumentDialog.getByRole('tab', { name: 'By hand' }).click()
  await instrumentDialog.getByLabel('Name').fill('E2E Stock')
  await instrumentDialog.getByLabel(/^ISIN/).fill('US0378331005')
  await instrumentDialog.getByRole('button', { name: 'Add instrument' }).click()
  await expect(instrumentDialog).toBeHidden()

  await page.getByRole('link', { name: 'Transactions' }).click()
  await expect(page.getByText('No transactions yet')).toBeVisible()

  async function buy(date: string, units: string, price: string) {
    await page.getByRole('button', { name: 'Add transaction' }).first().click()
    const dialog = page.getByRole('dialog', { name: 'Add transaction' })
    await dialog.getByLabel('Trade date').fill(date)
    await dialog.getByLabel('Instrument').selectOption({ index: 1 })
    await dialog.getByLabel('Units').fill(units)
    await dialog.getByLabel('Price per unit').fill(price)
    await dialog.getByLabel('Fees', { exact: true }).fill('1')
    await dialog.getByRole('button', { name: 'Save transaction' }).click()
    await expect(dialog).toBeHidden()
  }
  await buy('2025-01-10', '10', '100')
  await buy('2025-02-10', '5', '120')
  await expect(page.getByRole('row', { name: /Buy.*E2E Stock/ })).toHaveCount(2)

  // the sale: nothing is saved until the owner has seen the lots it uses
  await page.getByRole('button', { name: 'Add transaction' }).first().click()
  const dialog = page.getByRole('dialog', { name: 'Add transaction' })
  await dialog.getByLabel('Type').selectOption('sell')
  await dialog.getByLabel('Trade date').fill('2025-02-20')
  await dialog.getByLabel('Instrument').selectOption({ index: 1 })
  await dialog.getByLabel('Units').fill('12')
  await dialog.getByLabel('Price per unit').fill('130')

  const lots = dialog.getByRole('table', { name: 'Lots used by this sale' })
  await expect(lots.getByRole('row')).toHaveCount(4) // header, two lots, total
  await expect(lots).toContainText('2025-01-10')
  await expect(lots).toContainText('2025-02-10')
  await expect(lots).toContainText(euro('1\\.241,40')) // total cost
  await expect(lots).toContainText(euro('1\\.560,00')) // proceeds
  await expect(dialog.getByText('Realized result')).toContainText(euro('318,60'))
  await expect(dialog).toContainText('3 units with a cost basis of')
  await expect(dialog).toContainText(euro('360,60'))

  await dialog.getByRole('button', { name: 'Save transaction' }).click()
  await expect(dialog).toBeHidden()
  await expect(page.getByRole('row', { name: /Sell.*E2E Stock/ })).toBeVisible()

  // the position now agrees with the preview
  await page.getByRole('link', { name: 'Holdings' }).click()
  await expect(page.getByRole('heading', { name: 'Holdings' })).toBeVisible()
  const position = page.getByRole('row', { name: /E2E Stock/ })
  await expect(position).toContainText(euro('360,60')) // cost basis
})

// FR-TX-04: selling more than is held is refused with a plain explanation, and nothing is saved.
test('an oversell is explained in the preview and cannot be saved', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: 'Transactions' }).click()
  await page.getByRole('button', { name: 'Add transaction' }).first().click()
  const dialog = page.getByRole('dialog', { name: 'Add transaction' })
  await dialog.getByLabel('Type').selectOption('sell')
  await dialog.getByLabel('Trade date').fill('2025-03-01')
  await dialog.getByLabel('Instrument').selectOption({ index: 1 })
  await dialog.getByLabel('Units').fill('50')
  await dialog.getByLabel('Price per unit').fill('130')
  await expect(dialog.getByRole('alert')).toContainText(/3/)
  await dialog.getByRole('button', { name: 'Save transaction' }).click()
  await expect(dialog).toBeVisible() // still open: the server refused it
  await dialog.getByRole('button', { name: 'Close' }).click()
  await expect(page.getByRole('row', { name: /Sell.*E2E Stock/ })).toHaveCount(1)
})
