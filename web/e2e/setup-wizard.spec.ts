import { expect, test } from '@playwright/test'

const PASSWORD = 'a long e2e passphrase'

// FR-SY-01: a fresh install reaches the empty Home through the setup wizard (in well under 5 minutes).
test('fresh install: wizard to empty Home, then sign out and back in', async ({ page }) => {
  const started = Date.now()
  await page.goto('/')
  await expect(page).toHaveURL(/\/setup$/)
  await expect(page.getByRole('heading', { name: 'Set up Folio' })).toBeVisible()

  // 1. owner
  await page.getByLabel('Username').fill('Owner')
  await page.getByLabel('Password (12+ characters)').fill(PASSWORD)
  await page.getByLabel('Repeat password').fill(PASSWORD)
  await page.getByRole('button', { name: 'Next' }).click()

  // 2. preferences
  await expect(page.getByText('Step 2 of 5')).toBeVisible()
  await page.getByRole('button', { name: 'Next' }).click()

  // 3. first account
  await page.getByLabel('Account name').fill('Degiro')
  await page.getByLabel('Broker').fill('Degiro')
  await page.getByRole('button', { name: 'Next' }).click()

  // 4. providers: skippable
  await expect(page.getByText('Step 4 of 5')).toBeVisible()
  await page.getByRole('button', { name: 'Skip for now' }).click()

  // 5. notifications: skippable, finishes setup
  await expect(page.getByText('Step 5 of 5')).toBeVisible()
  await page.getByRole('button', { name: 'Skip for now' }).click()

  await expect(page).toHaveURL(/\/$/)
  await expect(
    page.getByText('Add your first instrument to start tracking your portfolio.'),
  ).toBeVisible()
  expect(Date.now() - started).toBeLessThan(5 * 60_000)

  // every page has an empty state
  await page.getByRole('link', { name: 'Holdings' }).click()
  await expect(page.getByText('No holdings yet')).toBeVisible()

  // sign out and back in
  await page.getByRole('button', { name: 'Sign out' }).first().click()
  await expect(page).toHaveURL(/\/login$/)
  await page.getByLabel('Username').fill('owner')
  await page.getByLabel('Password').fill(PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('navigation', { name: 'Main navigation' })).toBeVisible()
})

test('settings: a saved key is shown masked, never in full', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('Username').fill('owner')
  await page.getByLabel('Password').fill(PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await page.getByRole('link', { name: 'Settings' }).click()
  await page.getByRole('tab', { name: 'Providers' }).click()
  await page.getByLabel('EODHD API key').fill('eodhd-e2e-secret-1234')
  await page.getByRole('button', { name: 'Save' }).click()
  await expect(page.getByText('Settings saved.')).toBeVisible()
  const hint = page.getByText(/A value is saved/)
  await expect(hint).toContainText('1234')
  await expect(page.getByText('eodhd-e2e-secret-1234')).toHaveCount(0)
})
