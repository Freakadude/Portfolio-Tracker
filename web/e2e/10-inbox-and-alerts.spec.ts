import { expect, test } from '@playwright/test'
import { login } from './helpers'

// FR-INS-05, FR-NT-01, FR-NT-02, FR-NT-03, FR-SY-10, on what the earlier files left behind:
// E2E Watched, a hand-priced instrument last closed at 20, 10 units held.

test('a price alert fires on a new close and the bell updates without a reload (FR-INS-05, FR-NT-01)', async ({
  page,
}) => {
  await login(page)
  await page.getByRole('link', { name: 'Holdings', exact: true }).click()
  await page.getByRole('link', { name: 'E2E Watched' }).click()
  const alerts = page.getByRole('region', { name: 'Price alerts for E2E Watched' })
  await alerts.getByLabel('When it closes').selectOption('above')
  await alerts.getByLabel('Price', { exact: true }).fill('25')
  await alerts.getByRole('button', { name: 'Add alert' }).click()
  await expect(alerts).toContainText('Watching')
  await expect(page.getByRole('link', { name: 'Inbox: 0 unread' })).toBeVisible()

  // another client enters a close above the level; this page hears it from the server
  const csrf = decodeURIComponent(
    (await page.context().cookies()).find((c) => c.name === 'folio_csrf')?.value ?? '',
  )
  const id = page.url().split('/').pop()
  const today = new Date().toISOString().slice(0, 10)
  const saved = await page.request.post(`/api/v1/instruments/${id}/prices`, {
    headers: { 'X-CSRF-Token': csrf },
    data: { date: today, close: '26' },
  })
  expect(saved.ok()).toBeTruthy()
  await expect(page.getByRole('link', { name: 'Inbox: 1 unread' })).toBeVisible({ timeout: 15_000 })

  await page.getByRole('link', { name: 'Inbox: 1 unread' }).click()
  const inbox = page.getByRole('list', { name: 'Inbox' })
  const item = inbox.getByRole('listitem', { name: /E2E Watched closed above 25/ })
  await expect(item).toContainText('Waiting for Home Assistant') // the worker sends pushes
  await page.getByText(/More filters/).click()
  await page.getByLabel('Type').selectOption('alert')
  await expect(inbox.getByRole('listitem')).toHaveCount(1)
  await item.getByRole('button', { name: 'Mark as read' }).click()
  await expect(page.getByRole('link', { name: 'Inbox: 0 unread' })).toBeVisible()
  await item.getByRole('link', { name: 'Open' }).click()
  await expect(page).toHaveURL(new RegExp(`/holdings/${id}$`))
  await expect(alerts).toContainText('Fired')
})

test('notification settings: routing, a test push and the system information (FR-NT-02, FR-NT-03, FR-SY-10)', async ({
  page,
}) => {
  await login(page)
  await page.goto('/settings')
  await page.getByRole('tab', { name: 'Notifications' }).click()
  const cell = page.getByLabel('Low to ntfy')
  await expect(cell).not.toBeChecked()
  await cell.check()
  await page.getByRole('button', { name: 'Save routing' }).click()
  await expect(page.getByText('Routing saved; it applies to the next item.')).toBeVisible()
  await page.reload()
  await page.getByRole('tab', { name: 'Notifications' }).click()
  await expect(page.getByLabel('Low to ntfy')).toBeChecked()

  await page.getByRole('button', { name: 'Send a test to ntfy' }).click()
  await expect(page.getByText('Not set up: save the address and token first.')).toBeVisible()

  await page.getByRole('link', { name: 'System' }).click()
  const info = page.getByRole('region', { name: 'This installation' })
  await expect(info).toContainText('0.1.0')
  await expect(info).toContainText(/0 runs, 0[.,]00 of 5[.,]00 EUR/)
})
