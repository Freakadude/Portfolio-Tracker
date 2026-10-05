import { expect, test } from '@playwright/test'
import { euro, login } from './helpers'

// State left by the earlier files: the E2E Stock account holds 3 units after two buys and a sale
// (FIFO: remaining cost basis 360,60; average cost: 320,40). Net invested is
//   1.001,00 + 601,00 - 1.560,00 = 42,00.

test('home: a missing price is flagged, then value and result follow a hand-entered price', async ({
  page,
}) => {
  await login(page)
  await expect(page.getByRole('heading', { level: 1, name: 'Overview' })).toBeVisible()
  await expect(
    page.getByText('1 holding has no price yet and is left out of the value.'),
  ).toBeVisible()

  await page.getByRole('link', { name: 'Holdings' }).click()
  await page.getByRole('tab', { name: 'Instruments' }).click()
  await page
    .getByRole('row', { name: /E2E Stock/ })
    .getByRole('button', { name: 'Enter price' })
    .click()
  const dialog = page.getByRole('dialog', { name: /Enter a price for E2E Stock/ })
  await dialog.getByLabel('Closing price').fill('150')
  await dialog.getByRole('button', { name: 'Save price' }).click()
  await expect(dialog).toBeHidden()

  await page.getByRole('link', { name: 'Home' }).click()
  await page.getByRole('button', { name: 'All time' }).click()
  await expect(page.getByRole('button', { name: 'All time' })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
  const tile = (name: string) => page.getByRole('region', { name, exact: true })
  await expect(tile('Value')).toContainText(euro('450,00')) // 3 units x 150
  await expect(tile('Total result')).toContainText(euro('408,00')) // 450 - 42 put in
  await expect(page.getByText(/has no price yet/)).toHaveCount(0)

  // another period reloads without leaving the page
  await page.getByRole('button', { name: '1 week' }).click()
  await expect(page.getByRole('button', { name: '1 week' })).toHaveAttribute('aria-pressed', 'true')
  await expect(tile('Value')).toContainText(euro('450,00'))
})

test('accounts: switching to average cost warns, recalculates, and can be switched back', async ({
  page,
}) => {
  await login(page)
  await page.getByRole('link', { name: 'Settings' }).click()
  await page.getByRole('tab', { name: 'Accounts' }).click()
  const row = page.getByRole('row', { name: /Degiro/ })
  await expect(row).toContainText('First in, first out')

  async function switchTo(label: string, option: string) {
    await row.getByRole('button', { name: 'Edit' }).click()
    const dialog = page.getByRole('dialog', { name: /Edit Degiro/ })
    await dialog.getByLabel('Cost basis method').selectOption(option)
    const warned = new Promise<string>((resolve) =>
      page.once('dialog', (d) => {
        resolve(d.message())
        void d.accept()
      }),
    )
    await dialog.getByRole('button', { name: 'Save account' }).click()
    expect(await warned).toContain('recalculates every lot')
    await expect(dialog).toBeHidden()
    await expect(row).toContainText(label)
  }

  await switchTo('Average cost', 'AVG')
  await page.getByRole('link', { name: 'Holdings' }).click()
  await expect(page.getByRole('heading', { name: 'Holdings' })).toBeVisible()
  await expect(page.getByRole('row', { name: /E2E Stock/ })).toContainText(euro('320,40'))

  await page.getByRole('link', { name: 'Settings' }).click()
  await page.getByRole('tab', { name: 'Accounts' }).click()
  await switchTo('First in, first out', 'FIFO')
  await page.getByRole('link', { name: 'Holdings' }).click()
  await expect(page.getByRole('heading', { name: 'Holdings' })).toBeVisible()
  await expect(page.getByRole('row', { name: /E2E Stock/ })).toContainText(euro('360,60'))
})

test('system: usage, the refresh button and the audit log with old and new values', async ({
  page,
}) => {
  await login(page)
  await page.getByRole('link', { name: 'System' }).click()
  await expect(page.getByRole('heading', { name: 'System' })).toBeVisible()

  const usage = page.getByRole('table', { name: 'Calls made today per provider' })
  await expect(usage.getByRole('row', { name: /yahoo/i })).toBeVisible()

  await page.getByRole('button', { name: 'Refresh prices now' }).click()
  await expect(page.getByText(/Asked the worker to refresh prices/)).toBeVisible()

  const log = page.getByRole('table', { name: /Changes made to your data/ })
  await expect(log.getByRole('row', { name: /transaction #\d+/ }).first()).toBeVisible()
  // the method switch of the previous test is on record, with before and after
  await page.getByLabel('Kind of record').selectOption('account')
  await expect(log.getByRole('row').nth(1)).toContainText('cost_basis_method')
  await expect(log).toContainText('before FIFO after AVG')
})

test('insights: nothing waiting says so', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: 'Insights' }).click()
  await expect(page.getByText('No splits are waiting for you.')).toBeVisible()
  await expect(page.getByText('No dividends are waiting for you.')).toBeVisible()
})
