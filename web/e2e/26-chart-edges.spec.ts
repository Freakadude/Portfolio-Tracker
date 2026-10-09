import { expect, test, type Page } from '@playwright/test'
import { login } from './helpers'

// A chart in a dashboard widget runs from the left edge to the right edge of the widget, also
// after the widget has changed size (the grid measures itself after the first paint, and the page
// can be resized): it must not be left starting toward the middle.

/** How far across the chart's drawing the painted line reaches, as fractions of its width. */
async function paintedSpan(page: Page) {
  return page.evaluate(() => {
    const host = document.querySelector('[role="img"][aria-label^="Price chart"]')
    let left = Infinity
    let right = -Infinity
    let width = 0
    for (const canvas of Array.from(host?.querySelectorAll('canvas') ?? [])) {
      const context = canvas.getContext('2d')
      if (!context || canvas.width === 0) continue
      const { data } = context.getImageData(0, 0, canvas.width, canvas.height)
      // the line is the only thing in the colour of the series: opaque and saturated
      for (let x = 0; x < canvas.width; x++) {
        for (let y = 0; y < canvas.height; y += 2) {
          const i = (y * canvas.width + x) * 4
          const [r, g, b, a] = [data[i], data[i + 1], data[i + 2], data[i + 3]]
          if (a > 200 && b > 150 && b - r > 60 && b - g > 40) {
            left = Math.min(left, x)
            right = Math.max(right, x)
            width = canvas.width
            break
          }
        }
      }
    }
    return width === 0 ? null : { left: left / width, right: right / width }
  })
}

async function settled(page: Page) {
  let last = JSON.stringify(await paintedSpan(page))
  for (let i = 0; i < 12; i++) {
    await page.waitForTimeout(250)
    const next = JSON.stringify(await paintedSpan(page))
    if (next === last) return JSON.parse(next) as { left: number; right: number } | null
    last = next
  }
  return JSON.parse(last) as { left: number; right: number } | null
}

test('a price chart keeps running from edge to edge when its widget changes size', async ({
  page,
}) => {
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
    const close = (100 + 25 * Math.sin(day / 5) + day).toFixed(2)
    const saved = await page.request.post(`/api/v1/instruments/${fund!.id}/prices`, {
      headers: { 'X-CSRF-Token': csrf },
      data: { date, close },
    })
    expect(saved.ok()).toBeTruthy()
  }

  await page.goto('/dashboards/all')
  await page.getByLabel('Name').fill('Edge check')
  await page.getByRole('button', { name: 'Create dashboard' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Edge check' })).toBeVisible()
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
  await expect(page.getByRole('img', { name: /Price chart/ })).toBeVisible()

  const edges = async () => {
    const span = await settled(page)
    expect(span).not.toBeNull()
    // from (nearly) the left edge to (nearly) the right edge of the drawing
    expect(span!.left).toBeLessThan(0.1)
    expect(span!.right).toBeGreaterThan(0.75)
  }
  await edges()
  await page.setViewportSize({ width: 700, height: 900 }) // the widget gets narrower
  await edges()
  await page.setViewportSize({ width: 1500, height: 900 }) // and wider than it was
  await edges()
  // away and back
  await page.getByRole('link', { name: 'Holdings' }).click()
  await page.goBack()
  await expect(page.getByRole('img', { name: /Price chart/ })).toBeVisible()
  await edges()
})
