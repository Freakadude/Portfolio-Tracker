import { expect, test } from '@playwright/test'
import { login } from './helpers'

// A widget can be copied in edit mode, and the filter bars at the top of a dashboard can be
// taken off and brought back.

test('a widget is copied, and the timeframe filter is removed and added back', async ({ page }) => {
  await login(page)
  await page.goto('/dashboards/all')
  await page.getByLabel('Name').fill('Copies and bars')
  await page.getByRole('button', { name: 'Create dashboard' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Copies and bars' })).toBeVisible()

  await page.getByRole('button', { name: 'Add widget' }).first().click()
  await page.getByRole('searchbox', { name: 'Search widgets and figures' }).fill('note')
  await page.getByRole('button', { name: /^Note/ }).first().click()
  await page
    .getByRole('button', { name: /^Settings of/ })
    .first()
    .click()
  const dialog = page.getByRole('dialog', { name: /^Settings of/ })
  await dialog.getByLabel('Title', { exact: true }).fill('Plan')
  await dialog.getByRole('button', { name: 'Save' }).click()

  await page.getByRole('button', { name: 'Duplicate Plan' }).click()
  await expect(page.getByRole('region', { name: 'Plan', exact: true })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Plan (copy)', exact: true })).toBeVisible()

  // the timeframe filter goes, and stays gone after a reload
  const period = page.getByRole('group', { name: 'Period', exact: true })
  await expect(period).toBeVisible()
  await page.getByRole('button', { name: 'Remove the timeframe filter' }).click()
  await expect(period).toHaveCount(0)
  await expect(page.getByText('Timeframe filter removed.')).toBeVisible()
  await page.waitForTimeout(800) // saved a moment after the change
  await page.reload()
  await expect(page.getByRole('heading', { level: 1, name: 'Copies and bars' })).toBeVisible()
  await expect(page.getByRole('group', { name: 'Period', exact: true })).toHaveCount(0)
  await expect(page.getByText('Timeframe filter removed.')).toHaveCount(0) // not in view mode

  // edit mode offers it back
  await page.getByRole('button', { name: 'Edit', exact: true }).click()
  await page.getByRole('button', { name: 'Add it back' }).click()
  await expect(page.getByRole('group', { name: 'Period', exact: true })).toBeVisible()
})
