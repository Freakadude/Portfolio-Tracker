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
  const headers = await table.getByRole('columnheader').allTextContents()
  expect(headers.indexOf('Weight')).toBeLessThan(headers.indexOf('Value'))
  expect(headers).toEqual(expect.arrayContaining(['Target weight', 'Latest price']))
})
