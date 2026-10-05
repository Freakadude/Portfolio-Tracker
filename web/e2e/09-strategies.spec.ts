import { expect, test } from '@playwright/test'
import { login } from './helpers'

// FR-ST-01, FR-ST-02, FR-ST-05, on what the earlier files left behind: the sleeve "E2E Core"
// (target 100, band 5) holding E2E Stock (ISIN US0378331005, 5 units, last close 160), and
// E2E Watched (10 units, in no sleeve).

test('a strategy is written, refused with the line of its mistake, fixed and compared (FR-ST-01)', async ({
  page,
}) => {
  await login(page)
  await page.getByRole('link', { name: 'Strategies' }).click()
  await expect(page.getByText('No strategy yet')).toBeVisible()
  await page.getByRole('button', { name: 'New strategy' }).click()
  await expect(page.getByRole('heading', { level: 2, name: 'My strategy' })).toBeVisible()
  await expect(page.getByLabel('Members of sleeve 1')).toHaveValue('US0378331005') // from your sleeves

  await page.getByRole('tab', { name: 'YAML' }).click()
  const editor = page.getByLabel('Strategy as YAML')
  const starter = await editor.inputValue()
  expect(starter).toContain('id: "E2E Core"')

  await editor.fill(starter.replace('target_pct: null', 'target_pct: 140'))
  await page.getByRole('button', { name: 'Save as a new version' }).click()
  const problem = page.getByRole('alert')
  await expect(problem).toContainText(/Line \d+:/)
  await expect(problem).toContainText('less than or equal to 100')

  await editor.fill(
    starter.replace(
      'target_pct: null, soft_band_pp: null, hard_band_pp: null',
      'target_pct: 100, soft_band_pp: 5, hard_band_pp: 10',
    ),
  )
  await page.getByRole('button', { name: 'Save as a new version' }).click()
  await expect(page.getByText('Version 2', { exact: true })).toBeVisible()

  await page.getByRole('tab', { name: 'History' }).click()
  const diff = page.getByRole('table', { name: 'Changes from version 1 to version 2' })
  await expect(diff.locator('tr[data-kind="changed"]')).toContainText('target_pct: 100')
})

test('the active strategy owns the sleeve targets, and its orders become drafts to confirm (FR-ST-02, FR-ST-05)', async ({
  page,
}) => {
  await login(page)
  await page.goto('/strategies')
  await page.getByRole('button', { name: 'Make active' }).click()
  await expect(page.getByRole('navigation', { name: 'Your strategies' })).toContainText('Active')

  await page.goto('/settings')
  await page.getByRole('tab', { name: 'Sleeves' }).click()
  await expect(page.getByRole('note')).toContainText('active strategy My strategy')

  await page.goto('/strategies')
  await page.getByRole('tab', { name: 'Rules and signals' }).click()
  await expect(page.getByRole('table', { name: 'Rules' })).toContainText('Watching')

  await page.getByRole('tab', { name: 'Calculators' }).click()
  await page.getByLabel('New money (EUR)').fill('500')
  await page.getByRole('button', { name: 'Calculate' }).click()
  const orders = page.getByRole('table', { name: 'Orders' })
  await expect(orders.getByRole('row', { name: /E2E Stock/ })).toContainText('3') // 3 x 160
  await expect(page.getByText(/Left unspent/)).toContainText(/20[.,]00/)

  await page.getByRole('button', { name: 'Copy to draft transactions' }).click()
  await expect(page.getByText('1 draft transaction made.')).toBeVisible()
  await page.getByRole('link', { name: 'Confirm them on Insights' }).click()
  const proposed = page.getByRole('table', { name: 'Orders from your strategy' })
  await expect(proposed.getByRole('row', { name: /E2E Stock/ })).toBeVisible()
  await page.getByRole('button', { name: 'Confirm the order for E2E Stock' }).click()
  await expect(page.getByRole('table', { name: 'Orders from your strategy' })).toHaveCount(0)

  await page.getByRole('link', { name: 'Holdings', exact: true }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Holdings' })).toBeVisible()
  await expect(page.getByRole('row', { name: /E2E Stock/ })).toContainText('8') // 5 + 3
})
