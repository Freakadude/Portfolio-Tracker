import { expect, test } from '@playwright/test'
import { PASSWORD, login } from './helpers'
import { codeFor } from './totp'

// FR-SY-03 (the second factor) and FR-SY-07 (backups). The restore itself restarts the server, so
// it is covered by the integration tests; here the dialog is opened and left. The second factor
// is switched off again at the end, because the later files sign in with the password alone.

test('the second factor is set up, asked for at sign-in, and switched off with a recovery code', async ({
  page,
}) => {
  await login(page)
  await page.goto('/settings')
  await page.getByRole('tab', { name: 'Security' }).click()
  await expect(page.getByText('Off.')).toBeVisible()
  await page.getByRole('button', { name: 'Set up two-factor sign-in' }).click()
  await expect(page.getByAltText('QR code for your authenticator app')).toBeVisible()
  const secret = (await page.locator('code.select-all').innerText()).replace(/\s/g, '')
  expect(secret).toMatch(/^[A-Z2-7]{32}$/)

  await page.getByLabel('The six-digit code the app now shows').fill('000000')
  await page.getByRole('button', { name: 'Turn on' }).click()
  await expect(page.getByText(/That code is not right/)).toBeVisible()
  await page.getByLabel('The six-digit code the app now shows').fill(codeFor(secret))
  await page.getByRole('button', { name: 'Turn on' }).click()
  const codes = page.getByRole('list', { name: 'Your recovery codes' })
  await expect(codes).toBeVisible()
  const recovery = await codes.getByRole('listitem').allInnerTexts()
  expect(recovery).toHaveLength(10)
  await page.getByLabel('I have saved these codes').check()
  await page.getByRole('button', { name: 'Done' }).click()
  await expect(page.getByText('On. 10 recovery code(s) left.')).toBeVisible()

  // a new browser session: the password alone is no longer enough
  await page.context().clearCookies()
  await page.goto('/login')
  await page.getByLabel('Username').fill('owner')
  await page.getByLabel('Password').fill(PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()
  const code = page.getByLabel('Code from your authenticator app, or a recovery code')
  await expect(code).toBeVisible()
  await expect(page.getByRole('alert')).toContainText('Enter the code from your authenticator app')
  await code.fill('123456')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('alert')).toContainText('not right')
  // the next 30-second code is accepted (one step of drift), and the one that set it up is used
  await code.fill(codeFor(secret, 1))
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('navigation', { name: 'Main navigation' })).toBeVisible({
    timeout: 20_000,
  })

  // switch it off with a recovery code, so the other files can sign in with the password
  await page.goto('/settings')
  await page.getByRole('tab', { name: 'Security' }).click()
  await expect(page.getByText('On. 10 recovery code(s) left.')).toBeVisible()
  await page.getByLabel('Password').fill(PASSWORD)
  await page.getByLabel('A code from the app, or a recovery code').fill(recovery[0])
  await page.getByRole('button', { name: 'Turn off' }).click()
  await expect(page.getByText('Off.')).toBeVisible()
})

test('a backup is made and listed, and a restore waits for the typed word', async ({ page }) => {
  await login(page)
  await page.goto('/system')
  const section = page.getByRole('region', { name: 'Backups and restore' })
  await section.getByRole('button', { name: 'Back up now' }).click()
  const table = section.getByRole('table', { name: 'Backups on the server' })
  await expect(table.getByRole('row', { name: /folio-\d{8}-\d{6}\.db/ }).first()).toBeVisible()
  await expect(
    section
      .getByRole('link', { name: /Download folio-\d{8}-\d{6}\.db without the API keys/ })
      .first(),
  ).toBeVisible()

  await section
    .getByRole('button', { name: /Restore folio-/ })
    .first()
    .click()
  const dialog = page.getByRole('dialog', { name: 'Restore a backup' })
  await expect(dialog.getByText(/Everything in Folio is replaced/)).toBeVisible()
  const go = dialog.getByRole('button', { name: 'Restore and restart' })
  await expect(go).toBeDisabled()
  await dialog.getByLabel('Type RESTORE to confirm').fill('RESTORE')
  await expect(go).toBeEnabled() // not pressed: that would restart the server under the tests
})
