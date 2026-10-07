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

test('a claude.ai export is read and its chats about investing are offered', async ({ page }) => {
  await login(page)
  await page.goto('/strategies/assistant')
  await page.getByRole('tab', { name: 'From my chat export' }).click()
  const chat = (id: string, name: string, lines: string[]) => ({
    uuid: id,
    name,
    created_at: '2026-03-01T10:00:00Z',
    chat_messages: lines.map((text, i) => ({ sender: i % 2 ? 'assistant' : 'human', text })),
  })
  const conversations = [
    chat('a', 'World ETF and bonds', [
      'I want to invest in a world ETF for my retirement',
      'A broad index fund fits a long horizon',
      'Keep some bonds so a drawdown stays bearable',
    ]),
    chat('b', 'Pasta', ['How long do I boil spaghetti?', 'Nine minutes']),
  ]
  await page.getByLabel('Export file from claude.ai').setInputFiles({
    name: 'conversations.json',
    mimeType: 'application/json',
    buffer: Buffer.from(JSON.stringify(conversations)),
  })
  await expect(page.getByText(/2 chats found; 1 look like talks about investing/)).toBeVisible()
  await expect(page.getByLabel('World ETF and bonds')).toBeChecked()
  await expect(page.getByLabel('Pasta')).not.toBeChecked()
  await expect(page.getByRole('button', { name: 'Check the cost of 1 chat(s)' })).toBeVisible()
})
