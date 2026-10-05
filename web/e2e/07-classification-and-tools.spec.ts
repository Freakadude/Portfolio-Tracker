import { expect, test } from '@playwright/test'
import { login } from './helpers'

// FR-INS-04 (sleeves and classification), FR-INS-05 (watchlist), FR-PF-09 (what-if), on what the
// earlier files left behind: E2E Stock, 3 units in the Degiro account, last priced at 160.

test('a sleeve is created and an instrument classified into it (FR-INS-04)', async ({ page }) => {
  await login(page)
  await page.goto('/settings')
  await page.getByRole('tab', { name: 'Sleeves' }).click()
  await expect(page.getByText('No sleeves yet')).toBeVisible()

  await page.getByRole('button', { name: 'Add sleeve' }).first().click()
  const dialog = page.getByRole('dialog', { name: 'Add sleeve' })
  await dialog.getByLabel('Name').fill('E2E Core')
  await dialog.getByLabel('Target share (%)').fill('100')
  await dialog.getByLabel('Band (percentage points)').fill('5')
  await dialog.getByRole('button', { name: 'Save sleeve' }).click()
  await expect(dialog).toBeHidden()
  await expect(page.getByRole('row', { name: /E2E Core/ })).toContainText('100 %')

  await page.getByRole('link', { name: 'Holdings' }).click()
  await page.getByRole('tab', { name: 'Instruments' }).click()
  await page
    .getByRole('row', { name: /E2E Stock/ })
    .getByRole('button', { name: 'Edit' })
    .click()
  const edit = page.getByRole('dialog', { name: /Edit E2E Stock/ })
  await edit.getByLabel('Region').fill('Europe')
  await edit.getByLabel('Sleeve').selectOption('E2E Core')
  await edit.getByRole('button', { name: 'Save' }).click()
  await expect(edit).toBeHidden()

  // the holdings can now be grouped by the sleeve
  await page.getByRole('tab', { name: 'Positions' }).click()
  await page.getByLabel('Group by').selectOption('sleeve')
  await expect(page.getByRole('rowgroup').filter({ hasText: 'E2E Core' }).first()).toBeVisible()
})

test('the watchlist follows an instrument that is not held (FR-INS-05)', async ({ page }) => {
  await login(page)
  await page.goto('/holdings')
  await page.getByRole('button', { name: 'Add instrument' }).first().click()
  const add = page.getByRole('dialog', { name: 'Add instrument' })
  await add.getByRole('tab', { name: 'By hand' }).click()
  await add.getByLabel('Name').fill('E2E Watched')
  await add.getByRole('button', { name: 'Add instrument' }).click()
  await expect(add).toBeHidden()
  await page.getByRole('tab', { name: 'Instruments' }).click()
  await page
    .getByRole('row', { name: /E2E Watched/ })
    .getByRole('button', { name: 'Enter price' })
    .click()
  const price = page.getByRole('dialog', { name: /Enter a price for E2E Watched/ })
  await price.getByLabel('Closing price').fill('20')
  await price.getByRole('button', { name: 'Save price' }).click()
  await expect(price).toBeHidden()

  await page.getByRole('link', { name: 'Watchlist' }).click()
  await page.getByLabel('Instrument to watch').selectOption('E2E Watched')
  await page.getByRole('button', { name: 'Add to watchlist' }).click()
  const row = page.getByRole('row', { name: /E2E Watched/ })
  await expect(row).toContainText(/20,00/)

  await row.getByLabel('Note for E2E Watched').fill('wait for a dip')
  await row.getByLabel('Note for E2E Watched').blur()
  await page.reload()
  await expect(page.getByLabel('Note for E2E Watched')).toHaveValue('wait for a dip')

  await page
    .getByRole('row', { name: /E2E Watched/ })
    .getByRole('button', { name: 'Chart' })
    .click()
  await expect(page.getByRole('region', { name: 'E2E Watched' })).toBeVisible()

  // it stays on the watchlist only: no position appears
  await page.getByRole('link', { name: 'Holdings' }).click()
  await expect(page.getByRole('row', { name: /E2E Watched/ })).toHaveCount(0)

  await page.getByRole('link', { name: 'Watchlist' }).click()
  await page.getByRole('button', { name: 'Remove E2E Watched from the watchlist' }).click()
  await expect(page.getByRole('row', { name: /E2E Watched/ })).toHaveCount(0)
})

test('what-if shows the cash a trade needs and leaves the ledger alone (FR-PF-09)', async ({
  page,
}) => {
  await login(page)
  await page.getByRole('link', { name: 'Holdings' }).click()
  await page.getByRole('link', { name: 'What if…' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'What if' })).toBeVisible()

  // an incomplete row is named, nothing is sent
  await page.getByRole('button', { name: 'Show the result' }).click()
  await expect(page.getByRole('alert')).toContainText('Trade 1: choose an instrument.')

  await page.getByLabel('Instrument').selectOption('E2E Stock')
  await page.getByLabel('Units').fill('2')
  await page.getByLabel('Price (EUR)').fill('100')
  await page.getByRole('button', { name: 'Show the result' }).click()
  await expect(page.getByRole('status')).toContainText('You would need')
  await expect(page.getByRole('status')).toContainText(/200,00/)
  const positions = page.getByRole('table', { name: 'Positions before and after' })
  await expect(positions.getByRole('row', { name: /E2E Stock/ })).toContainText('5')

  // selling more than is held is refused with the numbers
  await page.getByLabel('Side').selectOption('sell')
  await page.getByLabel('Units').fill('50')
  await page.getByRole('button', { name: 'Show the result' }).click()
  await expect(page.getByRole('alert')).toContainText('You hold')

  // nothing was written: still 3 units
  await page.getByRole('link', { name: 'Holdings', exact: true }).click()
  await expect(page.getByRole('row', { name: /E2E Stock/ })).toContainText('3')
})
