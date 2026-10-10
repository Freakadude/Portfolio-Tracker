import { execSync } from 'node:child_process'
import { expect, test } from '@playwright/test'
import { login } from './helpers'

// A story card tells apart what it touches, what was reported, the impact, what could happen and
// what could be done, and a story that touches nothing is not listed (ADR 0061).

test.beforeAll(() => {
  execSync('uv run python scripts/e2e_seed_news.py', {
    cwd: '..',
    env: {
      ...process.env,
      FOLIO_SECRET_KEY: 'e2e-only-secret-key-0123456789abcdef0123456789',
      FOLIO_DB_URL: 'sqlite:///e2e-data/e2e.db',
    },
    stdio: 'pipe',
  })
})

test('the news card has its bands and a story that touches nothing is not listed', async ({
  page,
}) => {
  await login(page)
  await page.getByRole('link', { name: 'News' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'News' })).toBeVisible()

  const card = page.getByRole('article', { name: /export limits on chip tools widen/ })
  await expect(card).toBeVisible()
  await expect(card.getByRole('heading', { level: 3, name: 'What it touches' })).toBeVisible()
  await expect(card.getByRole('list', { name: 'Hits your holding directly' })).toBeVisible()
  await expect(card.getByRole('region', { name: 'What was reported' })).toContainText(
    'widened limits on exports',
  )
  await expect(card.getByRole('region', { name: 'Impact now' })).toContainText('Impact 74')
  await expect(card.getByRole('region', { name: 'Impact now' })).toContainText('Negative')
  const outlook = card.getByRole('region', { name: 'What could happen' })
  await expect(outlook).toContainText('Mid term')
  await expect(outlook).toContainText('High potential')
  await expect(card.getByRole('region', { name: 'What you could do' })).toContainText(
    'consider directing new money elsewhere first',
  )

  // the story concluded to touch nothing is simply not there
  await expect(page.getByRole('article', { name: /fishing quota debate/ })).toHaveCount(0)

  // the card is visibly a box of its own: a coloured stripe and a shadow, not a bare border
  const style = await card.evaluate((el) => {
    const s = getComputedStyle(el)
    return { stripe: parseFloat(s.borderLeftWidth), radius: parseFloat(s.borderTopLeftRadius) }
  })
  expect(style.stripe).toBeGreaterThanOrEqual(5)
  expect(style.radius).toBeGreaterThanOrEqual(8)
})
