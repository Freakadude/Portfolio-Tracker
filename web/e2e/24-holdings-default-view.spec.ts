import { expect, test } from '@playwright/test'
import { login } from './helpers'

// The Positions tab can keep its view (grouping, closed positions, sort order) as the default
// for this browser.

test('the holdings view is saved as the default, kept over a reload, and reset', async ({
  page,
}) => {
  await login(page)
  await page.getByRole('link', { name: 'Holdings' }).click()
  const group = page.getByLabel('Group by')
  await expect(group).toHaveValue('none')
  await group.selectOption('asset_class')
  await page.getByLabel('Show closed positions').check()
  await page.getByRole('button', { name: 'Save as default view' }).click()
  await expect(page.getByText('Saved as your default view.')).toBeVisible()

  await page.reload()
  await expect(page.getByLabel('Group by')).toHaveValue('asset_class')
  await expect(page.getByLabel('Show closed positions')).toBeChecked()
  await expect(page.getByRole('button', { name: 'Save as default view' })).toBeDisabled()

  await page.getByRole('button', { name: 'Back to the standard view' }).click()
  await expect(page.getByLabel('Group by')).toHaveValue('none')
  await page.reload()
  await expect(page.getByLabel('Group by')).toHaveValue('none')
  await expect(page.getByLabel('Show closed positions')).not.toBeChecked()
})
