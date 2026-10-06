import { expect, test } from '@playwright/test'
import { login } from './helpers'

// A figure such as the time-weighted return is found by searching Add widget, and the tile can
// explain how it was calculated, on the transactions the earlier files left behind.

test('a figure is found by searching, added, and explained step by step', async ({ page }) => {
  await login(page)
  await page.goto('/dashboards')
  await page.getByLabel('Name').fill('Returns check')
  await page.getByRole('button', { name: 'Create dashboard' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Returns check' })).toBeVisible()

  await page.getByRole('button', { name: 'Add widget' }).first().click()
  const search = page.getByRole('searchbox', { name: 'Search widgets and figures' })
  await search.fill('time-weighted')
  await expect(page.getByRole('button', { name: /^Key figure/ })).toHaveCount(0) // filtered away
  await page.getByRole('button', { name: /^Return \(time-weighted\)/ }).click()
  await expect(page.getByRole('region', { name: 'Return (time-weighted)' })).toBeVisible()

  await page.getByRole('button', { name: 'Add widget' }).first().click()
  await page.getByRole('searchbox', { name: 'Search widgets and figures' }).fill('xirr')
  await page.getByRole('button', { name: /^Return per year \(XIRR\)/ }).click()
  await expect(page.getByRole('region', { name: 'Return per year (XIRR)' })).toBeVisible()
  await page.getByRole('button', { name: 'Done' }).click()

  // the whole history, so there is something to measure whatever day the tests run on
  await page.getByRole('button', { name: 'All time' }).click()
  const tile = page.getByRole('region', { name: 'Return (time-weighted)' })
  await tile.getByRole('button', { name: 'How is this calculated?' }).click()
  const twr = page.getByRole('dialog', { name: 'How the time-weighted return is calculated' })
  await expect(
    twr.getByRole('table', { name: 'The stretches of the period and the growth of each' }),
  ).toBeVisible()
  await expect(twr.getByRole('row', { name: /All stretches together/ })).toBeVisible()
  await page.keyboard.press('Escape')

  const xirr = page.getByRole('region', { name: 'Return per year (XIRR)' })
  await xirr.getByRole('button', { name: 'How is this calculated?' }).click()
  const flows = page.getByRole('dialog', { name: 'How the return per year (XIRR) is calculated' })
  const table = flows.getByRole('table', { name: 'The money flows used for the XIRR' })
  await expect(table.getByRole('row', { name: /Value at the end/ })).toBeVisible()
  await expect(flows.getByRole('button', { name: 'Copy for a spreadsheet' })).toBeVisible()
})
