import { expect, test } from '@playwright/test'
import { login } from './helpers'

// The strategy helper's background notes (ADR 0048): the paths that need no AI.

test('background notes are written, switched off for the helper and deleted', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: 'Strategies' }).click()
  await page.getByRole('link', { name: 'Strategy helper' }).click()
  await expect(page.getByRole('heading', { name: 'My investing background' })).toBeVisible()

  const form = page.getByRole('form', { name: 'Write a note' })
  await form.getByLabel('Title').fill('Goals and horizon')
  await form.getByLabel('Note').fill('Retire in twenty years; a 30 percent fall would be hard.')
  await form.getByRole('button', { name: 'Add note' }).click()
  const row = page.getByRole('listitem').filter({ hasText: 'Goals and horizon' })
  await expect(row).toContainText('Written by me')
  await expect(page.getByText(/The helper reads \d+ of at most 12[.,]000 characters/)).toBeVisible()

  await row.getByLabel('Use in helper').uncheck()
  await expect(page.getByText(/The helper reads 0 of at most/)).toBeVisible()

  await page.getByRole('tab', { name: 'Ask Claude to write it (free)' }).click()
  await expect(page.getByLabel('Text to paste into Claude')).toContainText('Goals and time horizon')

  page.once('dialog', (d) => void d.accept())
  await row.getByRole('button', { name: 'Delete' }).click()
  await expect(page.getByText('Goals and horizon')).toHaveCount(0)
})
