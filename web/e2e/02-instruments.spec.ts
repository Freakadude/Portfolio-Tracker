import { expect, test } from '@playwright/test'
import { euro, login } from './helpers'

// FR-INS-02: a hand-priced instrument values from a hand-entered price. (Looking an ISIN up
// needs the market-data providers, which the end-to-end tests never contact.)
test('add a hand-priced instrument, give it a price, open it and delete it', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: 'Holdings' }).click()
  await expect(page.getByText('No holdings yet')).toBeVisible() // the empty state says what to do

  await page.getByRole('button', { name: 'Add instrument' }).first().click()
  const dialog = page.getByRole('dialog', { name: 'Add instrument' })
  await dialog.getByRole('tab', { name: 'By hand' }).click()
  await dialog.getByLabel('Name').fill('E2E Private bond')
  await dialog.getByLabel('Asset class').selectOption('BOND')
  await dialog.getByRole('button', { name: 'Add instrument' }).click()
  await expect(dialog).toBeHidden()

  await page.getByRole('tab', { name: 'Instruments' }).click()
  const row = page.getByRole('row', { name: /E2E Private bond/ })
  await expect(row).toBeVisible()
  await expect(row.getByText('Hand-priced')).toBeVisible()
  await expect(row.getByText('No price')).toBeVisible()

  await row.getByRole('button', { name: 'Enter price' }).click()
  const priceDialog = page.getByRole('dialog', { name: /Enter a price for E2E Private bond/ })
  await priceDialog.getByLabel('Closing price').fill('98.5')
  await priceDialog.getByRole('button', { name: 'Save price' }).click()
  await expect(row).toContainText(euro('98,50'))

  await row.getByRole('link', { name: 'E2E Private bond' }).click()
  await expect(page.getByRole('heading', { name: 'E2E Private bond' })).toBeVisible()
  await expect(page.getByText('You hold none of this instrument.')).toBeVisible()
  await expect(page.getByText('Latest close').locator('..')).toContainText(euro('98,50'))
  await expect(page.getByRole('img', { name: /Price chart/ })).toBeVisible()
  await page.getByRole('button', { name: 'Show data as a table' }).click()
  await expect(page.getByRole('table', { name: 'Closing prices' })).toContainText(euro('98,50'))

  await page.getByRole('link', { name: /Back to holdings/ }).click()
  await page.getByRole('tab', { name: 'Instruments' }).click()
  page.once('dialog', (d) => void d.accept())
  await page
    .getByRole('row', { name: /E2E Private bond/ })
    .getByRole('button', { name: 'Delete' })
    .click()
  await expect(page.getByRole('row', { name: /E2E Private bond/ })).toHaveCount(0)
})
