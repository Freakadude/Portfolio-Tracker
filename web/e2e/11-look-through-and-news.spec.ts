import { expect, test, type Page } from '@playwright/test'
import { login } from './helpers'

// FR-MD-09, FR-PF-05, FR-NW-01, FR-AG-09, on what the earlier files left behind. No site is
// contacted: the feed is served from the recorded fixtures on a local port (serve-fixtures.mjs).

async function csrf(page: Page) {
  return decodeURIComponent(
    (await page.context().cookies()).find((c) => c.name === 'folio_csrf')?.value ?? '',
  )
}

test('an ETF gets its holdings from a file and shows what it holds (FR-MD-09, FR-PF-05)', async ({
  page,
}) => {
  await login(page)
  const headers = { 'X-CSRF-Token': await csrf(page) }
  const accounts = await (await page.request.get('/api/v1/accounts')).json()
  const made = await page.request.post('/api/v1/instruments', {
    headers,
    data: { name: 'E2E World ETF', asset_class: 'ETF', manual: true, currency: 'EUR' },
  })
  expect(made.ok()).toBeTruthy()
  const etf = (await made.json())[0] ?? (await made.json())
  const id = etf.instrument?.id ?? etf.id
  const today = new Date().toISOString().slice(0, 10)
  await page.request.post(`/api/v1/instruments/${id}/prices`, {
    headers,
    data: { date: today, close: '100' },
  })
  const bought = await page.request.post('/api/v1/transactions', {
    headers,
    data: {
      account_id: accounts[0].id,
      instrument_id: id,
      type: 'buy',
      trade_date: today,
      quantity: '10',
      price: '100',
      fees: '0',
    },
  })
  expect(bought.status()).toBe(201)

  await page.goto(`/holdings/${id}`)
  await expect(page.getByRole('heading', { name: 'E2E World ETF' })).toBeVisible()
  const panel = page.getByRole('region', { name: 'What this fund holds' })
  await expect(panel.getByText('No holdings yet. Upload a file below.')).toBeVisible()
  await panel.getByRole('button', { name: 'Preview' }).click()
  await expect(panel.getByText('Choose a CSV file first.')).toBeVisible()

  await panel
    .getByLabel('Holdings file (CSV)')
    .setInputFiles('../tests/fixtures/lookthrough/ishares_style.csv')
  await panel.getByRole('button', { name: 'Preview' }).click()
  await expect(
    panel.getByText('Read as: 3 holdings, 99.5 % of the fund, dated 2026-10-03.'),
  ).toBeVisible()
  await expect(panel.getByText(/Left out \(cash and derivatives\): USD CASH/)).toBeVisible()
  await panel.getByRole('button', { name: 'Save these holdings' }).click()
  await expect(panel.getByText('Saved 3 holdings from 2026-10-03.')).toBeVisible()
  const top = panel.getByRole('table', { name: 'Largest holdings' })
  await expect(top.getByRole('row', { name: /ALPHA TECH INC/ })).toContainText('40.00')

  // what you own underneath, across the whole portfolio
  const through = await (
    await page.request.get('/api/v1/portfolio/look-through', { params: { top: '5' } })
  ).json()
  const alpha = through.exposures.find((e: { key: string }) => e.key === 'ALPHA TECH INC')
  expect(alpha.parts[0]).toMatchObject({ source: 'E2E World ETF', kind: 'look_through' })
  expect(Number(alpha.weight)).toBeGreaterThan(0)
})

test('a news feed is previewed before it is added, then listed and deleted (FR-NW-01)', async ({
  page,
}) => {
  await login(page)
  await page.goto('/settings')
  await page.getByRole('tab', { name: 'News' }).click()
  const table = page.getByRole('table', { name: 'News sources' })
  await expect(table.getByRole('row', { name: /ECB press releases/ })).toBeVisible() // ready-made
  await expect(table.getByRole('row', { name: /Federal Reserve press releases/ })).toBeVisible()

  await page.getByRole('button', { name: 'Add a source' }).click()
  await page.getByLabel('Name', { exact: true }).fill('E2E feed')
  await page.getByLabel('Feed address').fill('http://127.0.0.1:8766/ecb_press.xml')
  await page.getByRole('button', { name: 'Preview' }).click()
  await expect(page.getByText('The latest 10 of 15 items in this feed:')).toBeVisible({
    timeout: 20_000,
  })
  await expect(page.getByText(/Lane: Diagnostic Challenges/)).toBeVisible()
  await page
    .getByRole('form', { name: 'Add a source' })
    .getByRole('button', { name: 'Save' })
    .click()
  const row = table.getByRole('row', { name: /E2E feed/ })
  await expect(row).toBeVisible()

  page.once('dialog', (d) => void d.accept())
  await row.getByRole('button', { name: 'Delete E2E feed' }).click()
  await expect(table.getByRole('row', { name: /E2E feed/ })).toHaveCount(0)

  await page.getByRole('link', { name: 'News' }).click() // the page exists, and is empty for now
  await expect(page.getByRole('heading', { level: 1, name: 'News' })).toBeVisible()
  await expect(page.getByText('No news yet')).toBeVisible()
})

test('the agent says what it is waiting for (FR-AG-09)', async ({ page }) => {
  await login(page)
  await page.goto('/settings')
  await page.getByRole('tab', { name: 'Agent' }).click()
  await expect(page.getByText('Waiting for an API key')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Test the key' })).toBeDisabled()
  await page.getByRole('link', { name: 'System' }).click()
  await expect(page.getByText(/Add your Anthropic API key/)).toBeVisible()
})
