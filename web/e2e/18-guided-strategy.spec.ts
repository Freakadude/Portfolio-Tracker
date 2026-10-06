import { expect, test } from '@playwright/test'
import { login } from './helpers'

// FR-ST-01, the guided setup, on what the earlier files left behind: the sleeve "E2E Core"
// holding E2E Stock (ISIN US0378331005), and E2E Watched in no sleeve.

test('a strategy is made by answering a few questions (FR-ST-01)', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: 'Strategies' }).click()
  await page.getByRole('button', { name: 'Guided setup' }).click()
  await expect(page.getByText('Step 1 of 8')).toBeVisible()

  await page.getByLabel('What do you call this plan?').fill('Guided e2e')
  await page.getByRole('button', { name: 'Next' }).click()

  // the group comes from your sleeves, with its holding already in it
  await expect(page.getByLabel('Group of E2E Stock')).toHaveValue('E2E Core')
  await page.getByRole('button', { name: 'Next' }).click()

  await expect(page.getByRole('button', { name: 'Next' })).toBeDisabled() // targets are empty
  await page.getByRole('button', { name: "Use today's mix" }).click()
  await expect(page.getByLabel('Target of E2E Core')).toHaveValue('100')
  await page.getByRole('button', { name: 'Next' }).click()

  await page.getByLabel(/Tight/).check()
  await page.getByRole('button', { name: 'Next' }).click() // strictness
  await page.getByRole('button', { name: 'Next' }).click() // alerts
  await page.getByRole('button', { name: 'Skip' }).click() // regular investing
  await page.getByRole('button', { name: 'Next' }).click() // principles

  await expect(
    page.getByText(/E2E Core: target 100 %, 1 holding, warning at 2 points/),
  ).toBeVisible()
  await page.getByRole('button', { name: 'Save this strategy' }).click()

  await expect(page.getByRole('heading', { level: 2, name: 'Guided e2e' })).toBeVisible()
  await expect(page.getByText('Made with the guided setup')).toBeVisible()
  await expect(page.getByLabel('Target % of sleeve 1')).toHaveValue('100')
  await expect(page.getByLabel('Soft band of sleeve 1')).toHaveValue('2')
})
