import { expect, test } from '@playwright/test'
import { login } from './helpers'

// Every answer in the chat ends with what it cost (ADR 0059). The e2e database has one answered
// turn of a chat (scripts/e2e_seed_agent.py) that cost 0.0213 euro.

test('an answer in the chat ends with its cost', async ({ page }) => {
  await login(page)
  await page.evaluate(() => {
    window.localStorage.setItem('folio.chat.thread', 'e2e-chat-cost-1')
    window.localStorage.setItem('folio.chat.open', '1')
  })
  await page.reload()

  const panel = page.getByRole('complementary', { name: 'Ask Folio' })
  await expect(
    panel.getByText('It shows how far the portfolio is below its previous high.'),
  ).toBeVisible()
  await expect(panel.getByTestId('answer-cost')).toHaveText(/^This answer cost .*0[.,]02\.$/)
})
