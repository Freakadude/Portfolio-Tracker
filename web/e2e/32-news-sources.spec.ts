import { expect, test } from '@playwright/test'
import { login } from './helpers'

// The ready-made sources of ADR 0062 are listed in Settings, News; the SEC source and the
// per-share headlines wait for a contact email, which the owner enters in the same tab.

test('the new ready-made sources are listed and wait for the SEC contact email', async ({
  page,
}) => {
  await login(page)
  await page.goto('/settings')
  await page.getByRole('tab', { name: 'News' }).click()
  const table = page.getByRole('table', { name: 'News sources' })
  for (const name of [
    'Federal Reserve speeches and testimony',
    'US export controls (BIS, Federal Register)',
    'SEC filings for your holdings',
    'Nasdaq.com headlines for your shares',
  ]) {
    await expect(
      table.getByRole('row', { name: new RegExp(name.replace(/[()]/g, '.')) }),
    ).toBeVisible()
  }
  const sec = table.getByRole('row', { name: /SEC filings for your holdings/ })
  await expect(sec.getByText('Needs your contact email')).toBeVisible()

  const email = page.getByLabel(/Your email for SEC filings/)
  await email.fill('owner@example.com')
  await email.locator('xpath=ancestor::form[1]').getByRole('button', { name: 'Save' }).click()
  await expect(sec.getByText('Needs your contact email')).toHaveCount(0)
  await expect(sec.getByText('Working')).toBeVisible()
})
