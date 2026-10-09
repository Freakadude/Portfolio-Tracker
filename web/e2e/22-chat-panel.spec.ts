import { expect, test } from '@playwright/test'
import { login } from './helpers'

// The chat side panel opens from every page and stays where the owner left it (ADR 0049). The e2e
// server has no API key, so the paths up to a real answer are covered by the unit tests.

test('the chat panel opens on any page, follows the owner and is remembered', async ({ page }) => {
  await login(page)
  await expect(page.getByRole('complementary', { name: 'Ask Folio' })).toHaveCount(0)

  await page.getByRole('button', { name: 'Ask Folio' }).click()
  const panel = page.getByRole('complementary', { name: 'Ask Folio' })
  await expect(panel).toBeVisible()
  await expect(panel.getByRole('alert')).toContainText('off or has no API key')
  await expect(panel.getByLabel('Your message')).toBeDisabled()
  const box = await panel.boundingBox()
  expect(box?.width).toBeGreaterThan(300)
  expect(box?.width).toBeLessThan(420) // a side panel, not a page

  // it stays open while the owner moves around, and the page narrows beside it
  await page.getByRole('link', { name: 'Holdings' }).click()
  await expect(page).toHaveURL(/\/holdings$/)
  await expect(panel).toBeVisible()
  const main = await page.getByRole('main').boundingBox()
  expect((main?.x ?? 0) + (main?.width ?? 0)).toBeLessThanOrEqual((box?.x ?? 0) + 1)

  // remembered across a reload; closing hands the focus back to the button
  await page.reload()
  await expect(page.getByRole('complementary', { name: 'Ask Folio' })).toBeVisible()
  await page.getByRole('button', { name: 'Close the chat' }).click()
  await expect(page.getByRole('complementary', { name: 'Ask Folio' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Ask Folio' })).toBeFocused()

  // the keyboard shortcut works from a page too
  await page.keyboard.press('Control+/')
  await expect(page.getByRole('complementary', { name: 'Ask Folio' })).toBeVisible()
  await page.keyboard.press('Control+/')
  await expect(page.getByRole('complementary', { name: 'Ask Folio' })).toHaveCount(0)
})

test('on a narrow screen the panel covers the page instead of squeezing it', async ({ page }) => {
  await page.setViewportSize({ width: 420, height: 800 })
  await login(page)
  await page.getByRole('button', { name: 'Ask Folio' }).click()
  const panel = page.getByRole('complementary', { name: 'Ask Folio' })
  await expect(panel).toBeVisible()
  const box = await panel.boundingBox()
  expect(Math.round(box?.width ?? 0)).toBe(420)
  expect(Math.round(box?.height ?? 0)).toBe(800)
  await page.getByRole('button', { name: 'Close the chat' }).click()
  await expect(panel).toHaveCount(0)
})
