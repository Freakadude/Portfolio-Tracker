import { expect, test } from '@playwright/test'
import { login } from './helpers'

// The Home dashboard improvements asked for in October 2026, on what the earlier files left behind.

test('the value history says which period it shows and follows the dashboard period', async ({
  page,
}) => {
  await login(page)
  await page.getByRole('link', { name: 'Home' }).click()
  const group = page.getByRole('group', { name: 'Period' })
  await group.getByRole('button', { name: 'All time', exact: true }).click()
  await expect(page.getByText(/\(MAX\)\./)).toBeVisible()
  await group.getByRole('button', { name: '1 week', exact: true }).click()
  await expect(page.getByText(/\(1W\)\./)).toBeVisible()
})

test('Home says how fresh the prices behind its figures are', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: 'Home' }).click()
  await expect(page.getByTestId('price-status')).toContainText('Newest closing price')
})

test('the holdings widget columns are chosen, ordered and sorted in its settings', async ({
  page,
}) => {
  await login(page)
  await page.getByRole('link', { name: 'Home' }).click()
  await page.getByRole('button', { name: 'Edit', exact: true }).click()
  await page.getByRole('button', { name: 'Settings of Holdings' }).click()
  const dialog = page.getByRole('dialog', { name: /Settings of Holdings/ })
  await dialog.getByLabel('Add a column').selectOption({ label: 'Target weight' })
  await dialog.getByLabel('Add a column').selectOption({ label: 'Latest price' })
  await dialog.getByRole('button', { name: 'Move Weight up' }).click()
  await dialog.getByLabel('Sort by').selectOption({ label: 'Weight' })
  await dialog.getByLabel('Order').selectOption({ label: 'Lowest first' })
  await dialog.getByRole('button', { name: 'Save' }).click()
  await expect(dialog).toBeHidden()
  const table = page.getByRole('region', { name: 'Holdings', exact: true }).getByRole('table')
  await expect(table.getByRole('columnheader')).toHaveText([
    'Instrument',
    'Units',
    'Weight',
    'Value',
    'Unrealized',
    'Today',
    'Target weight',
    'Latest price',
  ])
})

test('Home can look at one instrument type or some holdings, and remembers the choice', async ({
  page,
}) => {
  await login(page)
  await page.getByRole('link', { name: 'Home' }).click()
  const row = page.getByRole('group', { name: 'Which holdings the figures are about' })
  const everything = row.getByRole('button', { name: 'Everything' })
  await expect(everything).toHaveAttribute('aria-pressed', 'true')
  const types = row.getByRole('group', { name: 'Instrument types' }).getByRole('button')
  const saved = page.waitForResponse(
    (r) => r.request().method() === 'PATCH' && r.url().includes('/api/v1/dashboards/'),
  )
  await types.first().click()
  await expect(types.first()).toHaveAttribute('aria-pressed', 'true')
  await expect(everything).toHaveAttribute('aria-pressed', 'false')
  await saved
  await page.reload() // saved with the dashboard
  await expect(types.first()).toHaveAttribute('aria-pressed', 'true')
  await everything.click()
  await expect(everything).toHaveAttribute('aria-pressed', 'true')
  await row.locator('summary').click()
  await row.getByRole('checkbox').first().check()
  await expect(row.getByText('1 holding')).toBeVisible()
  await everything.click()
})

test('instrument types are told apart in lists and on the instrument page', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: 'Holdings' }).click()
  await expect(page.locator('table [data-asset-class]').first()).toBeVisible()
  await page.getByRole('link', { name: 'E2E Stock' }).first().click()
  await expect(page.getByRole('heading', { level: 1, name: 'E2E Stock' })).toBeVisible()
  await expect(page.locator('span[data-asset-class][title]').first()).toBeVisible()
})

test('the Reconcile button says what it does, and the position sections fold away', async ({
  page,
}) => {
  await login(page)
  await page.getByRole('link', { name: 'Transactions' }).first().click()
  await expect(page.getByRole('button', { name: 'Reconcile', exact: true })).toHaveAttribute(
    'title',
    /Checks that Folio agrees with your broker/,
  )
  await page.getByRole('link', { name: 'Holdings' }).click()
  await page.getByRole('link', { name: 'E2E Stock' }).first().click()
  const history = page.getByRole('button', { name: 'Transactions', exact: true })
  await expect(history).toHaveAttribute('aria-expanded', 'true')
  await history.click()
  await expect(history).toHaveAttribute('aria-expanded', 'false')
  await history.click()
})

test('the Schedules settings explain themselves and move a job', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: 'Settings' }).click()
  await page.getByRole('tab', { name: 'Schedules' }).click()
  await expect(page.getByText('How do I change a time? Examples')).toBeVisible()
  await expect(page.getByRole('row', { name: /Value snapshots/ })).toContainText(
    'every day at 23:00',
  )
  await page.getByRole('button', { name: 'Change the time of Value snapshots' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('button', { name: 'weekdays at 19:30' }).click()
  await dialog.getByRole('button', { name: 'Save time' }).click()
  const row = page.getByRole('row', { name: /Value snapshots/ })
  await expect(row).toContainText('30 19 * * mon-fri')
  await expect(row).toContainText('set by you')
  await page.getByRole('button', { name: 'Put Value snapshots back to its normal time' }).click()
  await expect(row).toContainText('as normal')
})

test('each provider has an on/off switch', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: 'Settings' }).click()
  await page.getByRole('tab', { name: 'Providers' }).click()
  const fred = page.getByRole('listitem').filter({ hasText: 'US economic series' })
  await expect(fred.getByLabel('FRED is on')).toBeChecked()
  await fred.getByLabel('FRED is on').uncheck()
  await expect(fred.getByText('Off', { exact: true })).toBeVisible()
  await page.reload()
  await page.getByRole('tab', { name: 'Providers' }).click()
  await expect(fred.getByLabel('FRED is on')).not.toBeChecked()
  await fred.getByLabel('FRED is on').check()
  await expect(fred.getByLabel('FRED is on')).toBeChecked()
})
