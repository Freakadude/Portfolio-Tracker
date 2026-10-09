import { expect, test } from '@playwright/test'
import { login } from './helpers'

// The price chart widget: its settings preview keeps a steady size (it once grew without end),
// the timeframe and the price-changes views are chosen there, and a day without refresh prices
// says why (FR-DB-03).

test('the price chart settings: a steady preview, price changes and the 1 day timeframe', async ({
  page,
}) => {
  await login(page)
  // an instrument with a price to draw
  await page.getByRole('link', { name: 'Holdings' }).click()
  await page.getByRole('button', { name: 'Add instrument' }).first().click()
  const add = page.getByRole('dialog', { name: 'Add instrument' })
  await add.getByRole('tab', { name: 'By hand' }).click()
  await add.getByLabel('Name').fill('E2E Chart fund')
  await add.getByRole('button', { name: 'Add instrument' }).click()
  await expect(add).toBeHidden()
  await page.getByRole('tab', { name: 'Instruments' }).click()
  const row = page.getByRole('row', { name: /E2E Chart fund/ })
  await row.getByRole('button', { name: 'Enter price' }).click()
  const priced = page.getByRole('dialog', { name: /Enter a price for E2E Chart fund/ })
  await priced.getByLabel('Closing price').fill('98.5')
  await priced.getByRole('button', { name: 'Save price' }).click()
  await expect(row).toContainText('98')

  await page.goto('/dashboards')
  await page.getByLabel('Name').fill('Price check')
  await page.getByRole('button', { name: 'Create dashboard' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Price check' })).toBeVisible()

  await page.getByRole('button', { name: 'Add widget' }).first().click()
  await page.getByRole('searchbox', { name: 'Search widgets and figures' }).fill('price chart')
  await page
    .getByRole('button', { name: /^Price chart/ })
    .first()
    .click()
  await page.getByRole('button', { name: 'Settings of Price chart' }).click()

  const dialog = page.getByRole('dialog', { name: /Settings of Price chart/ })
  await dialog.getByLabel('Instrument').selectOption({ label: 'E2E Chart fund' })
  await dialog.getByLabel('Period', { exact: true }).selectOption('MAX')
  const chart = dialog.getByRole('img', { name: /Price chart/ })
  await expect(chart).toBeVisible()

  // the preview must not keep growing: the same height now and a couple of seconds later
  const first = (await chart.boundingBox())?.height ?? 0
  expect(first).toBeGreaterThan(100)
  expect(first).toBeLessThan(400)
  await page.waitForTimeout(2000)
  const later = (await chart.boundingBox())?.height ?? 0
  expect(Math.abs(later - first)).toBeLessThanOrEqual(2)

  // every way of looking at it is listed under Show; ticking a view stays steady too
  const show = dialog.getByRole('group', { name: 'Show' })
  for (const name of ['The price', 'Price changes (daily; per refresh for 1 day)']) {
    await expect(show.getByRole('checkbox', { name })).toBeVisible()
  }
  await show.getByRole('checkbox', { name: /^Price changes/ }).check()
  await show.getByRole('checkbox', { name: 'Change since the start' }).check()
  await page.waitForTimeout(1000)
  const withViews = (await chart.boundingBox())?.height ?? 0
  expect(withViews).toBeLessThan(400) // a legend row more takes some room, no more
  await page.waitForTimeout(1500)
  expect(Math.abs(((await chart.boundingBox())?.height ?? 0) - withViews)).toBeLessThanOrEqual(2)

  // one day uses the refresh prices; none are stored on a fresh install, and it says why
  await dialog.getByLabel('Period', { exact: true }).selectOption('1D')
  await expect(dialog.getByText(/No refresh prices are stored/)).toBeVisible()

  await dialog.getByLabel('Period', { exact: true }).selectOption('MAX')
  await expect(chart).toBeVisible()
  await dialog.getByRole('button', { name: 'Save' }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByRole('img', { name: /Price chart/ })).toBeVisible()
})

test('the key figure "Latest price" shows the price of one holding', async ({ page }) => {
  await login(page)
  await page.goto('/dashboards')
  await page.getByLabel('Name').fill('Latest price check')
  await page.getByRole('button', { name: 'Create dashboard' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Latest price check' })).toBeVisible()

  await page.getByRole('button', { name: 'Add widget' }).first().click()
  await page.getByRole('searchbox', { name: 'Search widgets and figures' }).fill('latest price')
  await page
    .getByRole('button', { name: /^Latest price/ })
    .first()
    .click()
  await page
    .getByRole('button', { name: /^Settings of/ })
    .first()
    .click()

  const dialog = page.getByRole('dialog', { name: /^Settings of/ })
  // without a holding it says what to choose
  await expect(dialog.getByText(/Choose a holding/)).toBeVisible()
  await dialog.getByLabel('Look at').selectOption('instrument')
  await dialog.getByLabel('Which one').selectOption({ label: 'E2E Chart fund' })
  await expect(dialog.getByText(/98[.,]50 EUR/)).toBeVisible()
  await dialog.getByLabel('Period', { exact: true }).selectOption('1D')
  await expect(dialog.getByText(/98[.,]50 EUR/)).toBeVisible() // no refresh prices: the close, with the reason
  await expect(dialog.getByText(/No refresh prices yet/)).toBeVisible()
})
