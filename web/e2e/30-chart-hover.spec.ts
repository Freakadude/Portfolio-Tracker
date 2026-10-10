import { expect, test } from '@playwright/test'
import { login } from './helpers'

// Over a line chart the value under the pointer is written in a chip above the cursor, in colours
// that are not the line's (ADR 0060), not on the price axis at the right.

test('the value under the pointer is shown above the cursor', async ({ page }) => {
  await page.setViewportSize({ width: 1300, height: 900 })
  await login(page)
  const csrf = decodeURIComponent(
    (await page.context().cookies()).find((c) => c.name === 'folio_csrf')?.value ?? '',
  )
  const list = await (await page.request.get('/api/v1/instruments')).json()
  const fund = (list as { id: number; name: string }[]).find((i) => i.name === 'E2E Chart fund')
  expect(fund).toBeTruthy()
  for (let day = 0; day < 40; day++) {
    const date = new Date(Date.UTC(2025, 0, 1 + day)).toISOString().slice(0, 10)
    // the same days as the chart-edge test may already be stored: that is fine
    await page.request.post(`/api/v1/instruments/${fund!.id}/prices`, {
      headers: { 'X-CSRF-Token': csrf },
      data: { date, close: (100 + 25 * Math.sin(day / 5) + day).toFixed(2) },
    })
  }

  await page.goto('/dashboards/all')
  await page.getByLabel('Name').fill('Hover check')
  await page.getByRole('button', { name: 'Create dashboard' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Hover check' })).toBeVisible()
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
  await dialog.getByRole('button', { name: 'Save' }).click()
  await page.getByRole('button', { name: 'Done' }).click()
  const chart = page.getByRole('img', { name: /Price chart/ })
  await expect(chart).toBeVisible()
  const tip = page.getByTestId('cursor-tip')
  await expect(tip).toBeHidden()

  const box = (await chart.boundingBox())!
  const x = box.x + box.width * 0.5
  const y = box.y + box.height * 0.6
  await page.mouse.move(x - 20, y)
  await page.mouse.move(x, y, { steps: 4 })
  await expect(tip).toBeVisible()
  const chip = (await tip.boundingBox())!
  expect(chip.y + chip.height).toBeLessThanOrEqual(y) // above the cursor
  expect(Math.abs(chip.x + chip.width / 2 - x)).toBeLessThan(40) // and on it, not at a side
  await expect(tip).toContainText(/\d/)

  // dark text colour of the page as the chip, which is not a blue or other series colour
  const [r, g, b] = (
    await tip.evaluate((el) => getComputedStyle(el).backgroundColor.match(/\d+/g) ?? [])
  ).map(Number)
  expect(Math.max(r, g, b) - Math.min(r, g, b)).toBeLessThan(40) // a neutral, not a hue

  await page.mouse.move(box.x - 30, box.y - 30) // off the chart
  await expect(tip).toBeHidden()
})
