import { expect, test, type Page } from '@playwright/test'
import { euro, login } from './helpers'

// FR-DB-01 to FR-DB-08, on what the earlier files left behind: E2E Stock, 3 units, priced at 150.

async function box(page: Page, name: string) {
  const b = await page.getByRole('region', { name, exact: true }).boundingBox()
  if (!b) throw new Error(`${name} is not on screen`)
  return b
}

/** The box once the grid has stopped moving (it re-measures its width after the first paint). */
async function settledBox(page: Page, name: string) {
  let last = await box(page, name)
  for (let i = 0; i < 10; i++) {
    await page.waitForTimeout(250)
    const next = await box(page, name)
    if (
      Math.abs(next.x - last.x) < 1 &&
      Math.abs(next.y - last.y) < 1 &&
      Math.abs(next.width - last.width) < 1
    ) {
      return next
    }
    last = next
  }
  return last
}

async function noHorizontalScroll(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(0)
}

test('a template builds a dashboard that works on any portfolio', async ({ page }) => {
  await login(page)
  await page.goto('/dashboards')
  await page.getByLabel('Start from').selectOption('risk')
  await page.getByRole('button', { name: 'Create dashboard' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Risk' })).toBeVisible()
  // every widget of the template draws something: a figure, a chart, or what to do next
  await expect(page.getByRole('region', { name: 'Volatility (1 year)' })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Drawdown' })).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0) // no widget failed
})

test('widgets are added, arranged by drag, and the arrangement survives a reload (desktop)', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  await login(page)
  await page.goto('/dashboards')
  await page.getByLabel('Name').fill('Workbench')
  await page.getByRole('button', { name: 'Create dashboard' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Workbench' })).toBeVisible()
  await expect(page.getByText('This dashboard is empty')).toBeVisible()

  await page.getByRole('button', { name: 'Add widget' }).first().click()
  await page.getByRole('button', { name: /^Note/ }).click()
  await expect(page.getByRole('region', { name: 'Note' })).toBeVisible()

  // settings: a title and some text, with a preview that follows
  await page.getByRole('button', { name: 'Settings of Note' }).click()
  const dialog = page.getByRole('dialog', { name: /Settings of Note/ })
  await dialog.getByLabel('Title').fill('Reminder')
  await dialog.getByLabel('Text').fill('Review the **allocation** monthly')
  await expect(dialog.getByText('allocation')).toBeVisible() // the preview
  await dialog.getByRole('button', { name: 'Save' }).click()
  await expect(dialog).toBeHidden()
  await expect(page.getByRole('region', { name: 'Reminder', exact: true })).toContainText(
    'Review the allocation monthly',
  )

  // a second widget, then move the first by dragging its handle
  await page.getByRole('button', { name: 'Add widget' }).first().click()
  await page.getByRole('button', { name: /^Key figure/ }).click()
  await expect(page.getByRole('region', { name: 'Value', exact: true })).toBeVisible()
  const before = await box(page, 'Reminder')
  const handle = page.getByRole('button', { name: 'Move Reminder', exact: true })
  const h = await handle.boundingBox()
  if (!h) throw new Error('no drag handle')
  await page.mouse.move(h.x + h.width / 2, h.y + h.height / 2)
  await page.mouse.down()
  await page.mouse.move(h.x + 400, h.y + 150, { steps: 12 })
  await page.mouse.up()
  await expect.poll(async () => (await box(page, 'Reminder')).x).not.toBeCloseTo(before.x, -1)

  // saved: leave edit mode, reload, and it is where it was put
  await page.getByRole('button', { name: 'Done' }).click()
  await page.reload()
  await expect(page.getByRole('region', { name: 'Reminder', exact: true })).toBeVisible()
  // the position is snapped to the grid when it is saved, so compare with where it started:
  // it is clearly to the right of its old place, and the same after another reload
  const settled = await settledBox(page, 'Reminder')
  expect(settled.x).toBeGreaterThan(before.x + 200)
  await page.reload()
  await expect(page.getByRole('region', { name: 'Reminder', exact: true })).toBeVisible()
  const again = await settledBox(page, 'Reminder')
  expect(Math.abs(again.x - settled.x)).toBeLessThan(2)
  expect(Math.abs(again.y - settled.y)).toBeLessThan(2)

  // the keyboard way: type a width in the settings
  await page.getByRole('button', { name: 'Edit' }).click()
  await page.getByRole('button', { name: 'Settings of Reminder' }).click()
  await page.getByRole('dialog').getByLabel('Width (columns)').fill('12')
  await page.getByRole('dialog').getByRole('button', { name: 'Save' }).click()
  await expect.poll(async () => (await box(page, 'Reminder')).width).toBeGreaterThan(900)
  await noHorizontalScroll(page)
})

test('the layout differs per breakpoint, and on a phone widgets stack in one column (FR-DB-02, FR-DB-08)', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  await login(page)
  await page.goto('/dashboards')
  await page.getByRole('link', { name: 'Workbench' }).click()
  await expect(page.getByRole('region', { name: 'Reminder', exact: true })).toBeVisible()
  const wide = await settledBox(page, 'Reminder')

  await page.setViewportSize({ width: 390, height: 844 })
  await expect.poll(async () => (await settledBox(page, 'Reminder')).width).toBeLessThan(wide.width)
  const reminder = await settledBox(page, 'Reminder')
  const figure = await settledBox(page, 'Value')
  // one column: both fill the width and sit one above the other
  expect(reminder.width).toBeGreaterThan(300)
  expect(Math.abs(reminder.x - figure.x)).toBeLessThan(4)
  expect(Math.abs(reminder.width - figure.width)).toBeLessThan(4)
  expect(
    reminder.y + reminder.height <= figure.y + 1 || figure.y + figure.height <= reminder.y + 1,
  ).toBe(true)
  await noHorizontalScroll(page)
})

test('every chart leads somewhere: a donut slice opens the holdings it stands for (FR-DB-06)', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  await login(page)
  await page.goto('/')
  const allocation = page.getByRole('region', { name: 'Allocation', exact: true })
  await expect(allocation).toBeVisible()
  // a single slice is a whole ring: click on the ring, not in its hole
  await allocation
    .getByRole('button', { name: /^.+: 100,0%/ })
    .click({ position: { x: 100, y: 6 } })
  await expect(page).toHaveURL(/\/holdings\?group_by=asset_class&value=/)
  await expect(page.getByRole('row', { name: /E2E Stock/ })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Show all positions' })).toBeVisible()
  await page.getByRole('button', { name: 'Show all positions' }).click()
  await expect(page).toHaveURL(/\/holdings$/)
})

test('every chart can be read as a table', async ({ page }) => {
  await login(page)
  await page.goto('/')
  const allocation = page.getByRole('region', { name: 'Allocation', exact: true })
  await allocation.getByRole('button', { name: 'Show data as a table' }).click()
  await expect(allocation.getByRole('table', { name: 'Allocation' })).toContainText('100,0%')
})

test('a new close appears without a reload (FR-DB-04)', async ({ page, context }) => {
  await login(page)
  await page.goto('/')
  const value = page.getByRole('region', { name: 'Value', exact: true })
  await expect(value).toContainText(euro('450,00')) // 3 units x 150

  // another client enters a new price; the open page hears about it from the server
  const cookies = await context.cookies()
  const csrf = decodeURIComponent(cookies.find((c) => c.name === 'folio_csrf')?.value ?? '')
  const list = await page.request.get('/api/v1/instruments')
  const stock = (await list.json()).find((i: { name: string }) => i.name === 'E2E Stock')
  const today = new Date().toISOString().slice(0, 10)
  const saved = await page.request.post(`/api/v1/instruments/${stock.id}/prices`, {
    headers: { 'X-CSRF-Token': csrf },
    data: { date: today, close: '160' },
  })
  expect(saved.ok()).toBeTruthy()
  await expect(value).toContainText(euro('480,00'), { timeout: 15_000 }) // 3 units x 160
})

test('dashboards are listed, duplicated, exported and deleted', async ({ page }) => {
  await login(page)
  await page.goto('/dashboards')
  const table = page.getByRole('table', { name: 'Your dashboards' })
  await expect(table.getByRole('row', { name: /Overview.*Opens on Home/ })).toBeVisible()
  await table
    .getByRole('row', { name: /^Workbench/ })
    .getByRole('button', { name: 'Duplicate' })
    .click()
  await expect(page.getByRole('heading', { level: 1, name: 'Workbench (copy)' })).toBeVisible()
  await page.goto('/dashboards')

  const download = page.waitForEvent('download')
  await table
    .getByRole('row', { name: /^Workbench \(copy\)/ })
    .getByRole('button', { name: 'Export' })
    .click()
  expect((await download).suggestedFilename()).toContain('Workbench_copy')

  page.once('dialog', (d) => void d.accept())
  await table
    .getByRole('row', { name: /^Workbench \(copy\)/ })
    .getByRole('button', { name: 'Delete' })
    .click()
  await expect(table.getByRole('row', { name: /^Workbench \(copy\)/ })).toHaveCount(0)
})
