import { execSync } from 'node:child_process'
import { expect, test } from '@playwright/test'
import { login } from './helpers'

// FR-AG-06 (the track record) and FR-NW-09 (the event calendar), on what the earlier files left
// behind: the recommendations of file 12. No model and no network is used; the worker is not
// running here, so the outcomes are seeded as the daily job would have written them.

test('the track record shows what became of the advice, by action type and by decision', async ({
  page,
}) => {
  execSync('uv run python scripts/e2e_seed_outcomes.py', {
    cwd: '..',
    env: {
      ...process.env,
      FOLIO_SECRET_KEY: 'e2e-only-secret-key-0123456789abcdef0123456789',
      FOLIO_DB_URL: 'sqlite:///e2e-data/e2e.db',
    },
    stdio: 'pipe',
  })
  await login(page)
  await page.goto('/insights')
  const section = page.getByRole('region', { name: "Track record of the agent's advice" })
  await expect(section).toBeVisible()
  const table = section.getByRole('table', {
    name: "Hit rate and price change of the agent's recommendations by action type",
  })
  const contribution = table.getByRole('row', { name: /Direct new money/ })
  await expect(contribution).toContainText('100%')
  await expect(contribution).toContainText('1 of 1')
  await expect(contribution).toContainText(/5[.,]00\s?%/)
  await expect(table.getByRole('row', { name: /Watch/ })).toContainText('not scored')
  await expect(section.getByText(/Price only/)).toBeVisible()

  await section.getByLabel('Horizon').selectOption('7')
  await expect(section.getByText('By what you decided, after 7 days')).toBeVisible()
})

test('events are added, changed and deleted on the calendar', async ({ page }) => {
  await login(page)
  await page.goto('/news?tab=calendar')
  await expect(page.getByRole('tab', { name: 'Calendar', selected: true })).toBeVisible()
  await expect(page.getByText(/The ready-made dates/)).toBeVisible()

  const day = new Date(Date.now() + 10 * 86400_000).toISOString().slice(0, 10)
  const moved = new Date(Date.now() + 12 * 86400_000).toISOString().slice(0, 10)
  await page.getByRole('button', { name: 'Add an event' }).click()
  let dialog = page.getByRole('dialog', { name: 'Add an event' })
  await dialog.getByRole('button', { name: 'Save event' }).click()
  await expect(dialog.getByText('This is required.').first()).toBeVisible()
  await dialog.getByLabel('Title').fill('E2E annual meeting')
  await dialog.getByLabel('Date').fill(day)
  await dialog.getByLabel('Note (optional)').fill('vote on the dividend')
  await dialog.getByRole('button', { name: 'Save event' }).click()
  const table = page.getByRole('table', { name: /Dated events/ })
  const row = table.getByRole('row', { name: /E2E annual meeting/ })
  await expect(row).toContainText(day)
  await expect(row).toContainText('in 10 days')
  await expect(row).toContainText('vote on the dividend')

  await page.getByRole('button', { name: 'Change E2E annual meeting' }).click()
  dialog = page.getByRole('dialog', { name: 'Change an event' })
  await dialog.getByLabel('Date').fill(moved)
  await dialog.getByRole('button', { name: 'Save event' }).click()
  await expect(table.getByRole('row', { name: /E2E annual meeting/ })).toContainText(moved)

  await page.getByRole('button', { name: 'Refresh dates' }).click()
  await expect(page.getByText(/Asked the worker to refresh/)).toBeVisible()

  page.once('dialog', (d) => void d.accept())
  await page.getByRole('button', { name: 'Delete E2E annual meeting' }).click()
  await expect(table.getByRole('row', { name: /E2E annual meeting/ })).toHaveCount(0)
})
