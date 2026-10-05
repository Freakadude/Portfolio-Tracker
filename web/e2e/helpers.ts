import { expect, type Page } from '@playwright/test'

export const PASSWORD = 'a long e2e passphrase'

/** Sign in as the owner created by the setup-wizard test (files run in numbered order). */
export async function login(page: Page) {
  await page.goto('/login')
  await page.getByLabel('Username').fill('owner')
  await page.getByLabel('Password').fill(PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()
  // generous: password hashing is slow on a busy CI runner
  await expect(page.getByRole('navigation', { name: 'Main navigation' })).toBeVisible({
    timeout: 20_000,
  })
}

/** Euro amounts use a non-breaking space in the Dutch format, so match with a pattern. */
export const euro = (digits: string) => new RegExp(`€\\s*${digits}`)
