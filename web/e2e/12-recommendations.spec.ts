import { execSync } from 'node:child_process'
import { expect, test } from '@playwright/test'
import { login } from './helpers'

// FR-AG-05, FR-AG-04 and the recommendation accept of NFR-12, on what the earlier files left
// behind: the active strategy "My strategy" and E2E Stock (8 units, last close 160). The run itself
// is covered by the integration tests with a scripted model; here the seed script writes what a run
// leaves behind (its calculation comes from the app's own calculator), and the owner decides.

test.beforeAll(() => {
  execSync('uv run python scripts/e2e_seed_agent.py', {
    cwd: '..',
    env: {
      ...process.env,
      FOLIO_SECRET_KEY: 'e2e-only-secret-key-0123456789abcdef0123456789',
      FOLIO_DB_URL: 'sqlite:///e2e-data/e2e.db',
    },
    stdio: 'pipe',
  })
})

test('advice is accepted as draft transactions, confirmed, and a rejection keeps its reason', async ({
  page,
}) => {
  await login(page)
  await page.goto('/insights')
  const card = page.getByRole('article', { name: 'Direct new money to E2E Core' })
  await expect(card).toBeVisible()
  await expect(card.getByText('AI-generated', { exact: true })).toBeVisible()
  await expect(page.getByText(/AI-generated, not financial advice/).first()).toBeVisible()
  await expect(card.getByRole('table', { name: 'Orders from the calculator' })).toContainText(
    'E2E Stock',
  )
  await expect(card.getByText('Departs from your principles')).toHaveCount(0)
  await card.getByText('Evidence and sources').click()
  await expect(card.getByText('Allocator result')).toBeVisible()

  await card.getByRole('button', { name: /^Accept and make draft transactions/ }).click()
  // the card leaves the open list at once, so the proof is the order list it created
  const drafts = page.getByRole('table', { name: 'Orders from your strategy' })
  await expect(drafts.getByRole('row', { name: /E2E Stock/ })).toBeVisible()
  await page.getByRole('button', { name: 'Confirm the order for E2E Stock' }).click()
  await page.getByRole('link', { name: 'Holdings', exact: true }).click()
  await expect(page.getByRole('row', { name: /E2E Stock/ })).toContainText('11') // 8 + 3

  // the other item is rejected with a reason, which stays on record
  await page.goto('/insights')
  await expect(page.getByRole('article', { name: 'Direct new money to E2E Core' })).toHaveCount(0)
  const watch = page.getByRole('article', { name: 'Watch E2E Watched' })
  await watch.getByRole('button', { name: /^Reject/ }).click()
  await watch.getByLabel('Why? (optional, one line)').fill('I know about it already.')
  await watch.getByRole('button', { name: 'Reject it' }).click()
  await expect(page.getByText('Nothing is waiting for a decision.')).toBeVisible()
  await page.getByLabel('Show', { exact: true }).selectOption('rejected')
  await expect(page.getByText('Your reason: I know about it already.')).toBeVisible()
  await page.getByLabel('Show', { exact: true }).selectOption('accepted')
  await expect(page.getByRole('article', { name: 'Direct new money to E2E Core' })).toBeVisible()
})

test('the System page lists the agent run and opens its trace (FR-AG-04)', async ({ page }) => {
  await login(page)
  await page.goto('/system')
  const table = page.getByRole('table', { name: 'Agent runs' })
  const row = table.getByRole('row', { name: /Daily review/ })
  await expect(row).toContainText('0.0123')
  await expect(row).toContainText('2 shown, 1 refused')
  await row.getByRole('button', { name: /Trace of run/ }).click()
  const trace = page.getByRole('region', { name: /Trace of run/ })
  await expect(trace).toContainText('4300 tokens in, 650 out')
  const verdicts = trace.getByRole('list', { name: 'Verdicts on each recommendation' })
  await expect(verdicts).toContainText('Refused')
  await expect(verdicts).toContainText('a trade needs a calculation from this run')
  await expect(trace.getByText('Tool calls (2)')).toBeVisible()
})
