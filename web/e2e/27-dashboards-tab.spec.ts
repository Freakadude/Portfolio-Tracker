import { expect, test } from '@playwright/test'
import { login } from './helpers'

// A dashboard can be chosen for the Dashboards tab; "All dashboards" still shows the list. And a
// note can show only its title, in a size and on a background of the owner's choosing.

test('the Dashboards tab opens the chosen dashboard, and All dashboards shows the list', async ({
  page,
}) => {
  await login(page)
  await page.goto('/dashboards/all')
  await page.getByLabel('Name').fill('Tab view')
  await page.getByRole('button', { name: 'Create dashboard' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Tab view' })).toBeVisible()

  const choose = page.getByRole('button', { name: 'Open this from the Dashboards tab' })
  await expect(choose).toHaveAttribute('aria-pressed', 'false')
  await choose.click()
  await expect(page.getByRole('button', { name: 'Dashboards tab opens this one' })).toHaveAttribute(
    'aria-pressed',
    'true',
  )

  await page.getByRole('link', { name: 'Holdings', exact: true }).click() // go elsewhere first
  await page.getByRole('link', { name: 'Dashboards', exact: true }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Tab view' })).toBeVisible()

  await page.getByRole('link', { name: 'All dashboards' }).click()
  await expect(page).toHaveURL(/\/dashboards\/all$/)
  await expect(page.getByRole('heading', { level: 1, name: 'Dashboards' })).toBeVisible()

  // clear the choice again so the other files see the list on /dashboards
  await page.goto('/dashboards/all')
  await page.getByRole('link', { name: 'Tab view' }).click()
  await page.getByRole('button', { name: 'Dashboards tab opens this one' }).click()
  await page.getByRole('link', { name: 'Dashboards', exact: true }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Dashboards' })).toBeVisible()
})

test('a note can show only its title, large, on a coloured background', async ({ page }) => {
  await login(page)
  await page.goto('/dashboards/all')
  await page.getByLabel('Name').fill('Heading check')
  await page.getByRole('button', { name: 'Create dashboard' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Heading check' })).toBeVisible()
  await page.getByRole('button', { name: 'Add widget' }).first().click()
  await page.getByRole('searchbox', { name: 'Search widgets and figures' }).fill('note')
  await page.getByRole('button', { name: /^Note/ }).first().click()
  await page
    .getByRole('button', { name: /^Settings of/ })
    .first()
    .click()
  const dialog = page.getByRole('dialog', { name: /^Settings of/ })
  await dialog.getByLabel('Title', { exact: true }).fill('Long term')
  await dialog.getByLabel('Text').fill('Not shown when only the title is')
  await dialog.getByLabel('Show only the title').check()
  await dialog.getByLabel('Title size').selectOption('xlarge')
  await dialog.getByLabel('Background').selectOption('green')
  await dialog.getByRole('button', { name: 'Save' }).click()
  await page.getByRole('button', { name: 'Done' }).click()

  const note = page.getByRole('region', { name: 'Long term', exact: true })
  await expect(note.getByRole('heading', { name: 'Long term' })).toHaveClass(/text-4xl/)
  await expect(note.getByText('Not shown when only the title is')).toHaveCount(0)
  await expect(note).toHaveAttribute('style', /color-mix/)
})
