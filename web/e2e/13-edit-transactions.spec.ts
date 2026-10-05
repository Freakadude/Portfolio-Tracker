import { expect, test, type Page } from '@playwright/test'
import { login } from './helpers'

// FR-TX-14: a stored transaction is edited from the position page, the amount is calculated while
// typing, and the position follows. On what the earlier files left behind (an account).

async function csrf(page: Page) {
  return decodeURIComponent(
    (await page.context().cookies()).find((c) => c.name === 'folio_csrf')?.value ?? '',
  )
}

test('a buy is edited from the position page and the amount follows (FR-TX-14)', async ({
  page,
}) => {
  await login(page)
  const headers = { 'X-CSRF-Token': await csrf(page) }
  const accounts = await (await page.request.get('/api/v1/accounts')).json()
  const made = await page.request.post('/api/v1/instruments', {
    headers,
    data: { name: 'E2E Edit Fund', asset_class: 'ETF', manual: true, currency: 'EUR' },
  })
  expect(made.ok()).toBeTruthy()
  const body = await made.json()
  const created = Array.isArray(body) ? body[0] : body
  const id = created.instrument?.id ?? created.id
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
      fees: '2',
    },
  })
  expect(bought.status()).toBe(201)

  await page.goto(`/holdings/${id}`)
  const history = page.getByRole('region', { name: 'Transactions' })
  await history.getByRole('button', { name: `Edit the Buy of ${today}` }).click()
  const dialog = page.getByRole('dialog', { name: 'Edit transaction' })

  // the stored values, and the amount already worked out
  await expect(dialog.getByLabel('Units')).toHaveValue('10')
  await expect(dialog.getByLabel('Price per unit')).toHaveValue('100')
  const amount = dialog.getByRole('table', { name: 'How the amount in euros is calculated' })
  await expect(amount).toContainText(/Total paid.*1[.,]?002[.,]00/)

  // units and price change, the amount recalculates before anything is saved
  await dialog.getByLabel('Units').fill('12')
  await dialog.getByLabel('Price per unit').fill('101')
  await expect(amount).toContainText(/Total paid.*1[.,]?214[.,]00/)
  await dialog.getByRole('button', { name: 'Save transaction' }).click()
  await expect(dialog).toHaveCount(0)
  const row = history.getByRole('row', { name: new RegExp(`${today} Buy`) })
  await expect(row).toContainText('12')
  await expect(row).toContainText(/1[.,]?214[.,]00/)
  await expect(page.getByText('Cost basis').locator('..')).toContainText(/1[.,]?214[.,]00/)

  // the type can be changed too; a sale of units that were never bought is refused in words
  await history.getByRole('button', { name: `Edit the Buy of ${today}` }).click()
  await dialog.getByLabel('Type').selectOption('sell')
  await dialog.getByRole('button', { name: 'Save transaction' }).click()
  await expect(dialog.getByText(/only 0 are held/)).toBeVisible()
  await dialog.getByRole('button', { name: /close/i }).click()
  await expect(history.getByRole('row', { name: new RegExp(`${today} Buy`) })).toBeVisible()

  // and the row can be deleted from here
  page.once('dialog', (d) => void d.accept())
  await history.getByRole('button', { name: `Delete the Buy of ${today}` }).click()
  await expect(page.getByText('You hold none of this instrument.')).toBeVisible()
})
