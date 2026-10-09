import { expect, test } from '@playwright/test'
import { login } from './helpers'

// Insights is a set of sections with clear headers that open and close, and the question box
// is gone from it (the chat panel answers questions from any page).

test('Insights sections close from their header and stay closed after a reload', async ({
  page,
}) => {
  await login(page)
  await page.goto('/insights')
  await expect(page.getByRole('heading', { level: 2, name: /^Inbox/ })).toBeVisible()
  await expect(page.getByText('Ask the portfolio')).toHaveCount(0)

  const inbox = page.getByRole('region', { name: 'Inbox' })
  const toggle = inbox.getByRole('button', { name: 'Inbox' })
  await expect(toggle).toHaveAttribute('aria-expanded', 'true')
  await toggle.click()
  await expect(toggle).toHaveAttribute('aria-expanded', 'false')
  await expect(inbox.getByRole('list', { name: 'Inbox' })).toBeHidden()

  await page.reload()
  await expect(
    page.getByRole('region', { name: 'Inbox' }).getByRole('button', { name: 'Inbox' }),
  ).toHaveAttribute('aria-expanded', 'false')
})

test('an inbox card has a title, a summary and buttons, and its details open', async ({ page }) => {
  await login(page)
  await page.goto('/insights')
  // the price alert of an earlier test left an item behind
  const card = page.getByRole('listitem', { name: /E2E Watched closed above 25/ })
  await expect(card).toBeVisible()
  await expect(card.getByRole('heading', { level: 3 })).toContainText('E2E Watched closed above')
  await expect(card.getByRole('link', { name: /^Open position/ })).toBeVisible()
  await card.getByText('Show details').click()
  await expect(card).toContainText('Home Assistant')
})
