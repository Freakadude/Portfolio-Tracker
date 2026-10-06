import { readFileSync } from 'node:fs'
import { expect, test } from '@playwright/test'
import { login } from './helpers'

// FR-PF-11 (tax support), FR-TX-13 (export), FR-PF-12 (projection), FR-ST-06 (backtest) on what
// the earlier files left behind.

test('the tax-support report shows the year and downloads as CSV', async ({ page }) => {
  await login(page)
  await page.goto('/reports?tab=tax')
  const year = new Date().getFullYear()
  const report = page.getByRole('article', { name: `Tax support for ${year}` })
  await expect(report).toBeVisible()
  const table = report.getByRole('table', { name: `Figures for ${year} for a tax return` })
  await expect(table.getByRole('row', { name: /Value on .*-01-01/ })).toBeVisible()
  await expect(table.getByRole('row', { name: /Money put in/ })).toBeVisible()
  await expect(table.getByRole('row', { name: /Change in unrealized result/ })).toBeVisible()
  await expect(
    report.getByRole('table', { name: /Holdings on .*-12-31|Holdings on / }).first(),
  ).toBeVisible()
  await expect(report.getByText(/not tax advice/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Print or save as PDF' })).toBeVisible()

  const download = page.waitForEvent('download')
  await page.getByRole('link', { name: 'Download CSV' }).click()
  const file = await (await download).path()
  const lines = readFileSync(file, 'utf-8').split('\n')
  expect(lines[0]).toBe('section,item,isin,quantity,value_eur,cost_basis_eur')
  expect(lines.some((l) => l.startsWith('summary,Realized result,'))).toBe(true)
})

test('the transactions export has the columns the import recognises', async ({ page }) => {
  await login(page)
  await page.goto('/reports?tab=export')
  const download = page.waitForEvent('download')
  await page.getByRole('link', { name: 'Download CSV' }).first().click()
  const file = await (await download).path()
  const lines = readFileSync(file, 'utf-8').trim().split('\n')
  expect(lines[0]).toBe(
    'date,type,isin,name,ticker,account,quantity,price,currency,fx_rate_to_eur,fees,fees_currency,taxes,amount,reference,note',
  )
  expect(lines.length).toBeGreaterThan(2) // the earlier files left transactions
  await expect(page.getByText(/import the file again/)).toBeVisible()
})

test('the projection draws a band for the assumptions and reads as a table', async ({ page }) => {
  await login(page)
  await page.goto('/reports?tab=projection')
  await page.getByLabel('Years ahead (1 to 40)').fill('5')
  await page.getByLabel('Added each month (€)').fill('100')
  await page.getByLabel('Expected return a year (%)').fill('4')
  await expect(page.getByRole('region', { name: 'Projected value of the portfolio' })).toBeVisible({
    timeout: 20_000,
  })
  await expect(
    page.getByText(/Assumptions: start .*100 a month.*4[.,]0 % expected return/),
  ).toBeVisible()
  await expect(page.getByText(/the median is/)).toBeVisible()
  await page.getByRole('button', { name: 'Show data as a table' }).click()
  const table = page.getByRole('table', { name: 'Projected value of the portfolio by month' })
  expect(await table.getByRole('row').count()).toBeGreaterThan(55)
  await page.getByLabel('Years ahead (1 to 40)').fill('99')
  await expect(page.getByText(/horizon is 1 to 40 whole years/)).toBeVisible()
})

test('a rule backtest lists what it checked', async ({ page }) => {
  await login(page)
  await page.goto('/strategies')
  await page.getByRole('tab', { name: 'Backtest' }).click()
  await page.getByRole('button', { name: 'Run the backtest' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'trading days checked' })).toBeVisible({
    timeout: 20_000,
  })
  await expect(page.getByText(/Nothing is saved or sent/).first()).toBeVisible()
})
