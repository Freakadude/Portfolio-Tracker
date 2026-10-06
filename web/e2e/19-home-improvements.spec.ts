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
