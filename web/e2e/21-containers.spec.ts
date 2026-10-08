import { expect, test } from '@playwright/test'
import { login } from './helpers'

// The System page says which commit each container runs and for how long (FR-SY-10).

test('the System page shows the web container uptime and what it knows of the worker', async ({
  page,
}) => {
  await login(page)
  await page.getByRole('link', { name: 'System' }).click()
  const web = page.getByTestId('web')
  await expect(web).toContainText('Web container')
  await expect(web).toContainText('Running for')
  await expect(web).toContainText('Development build') // an unpackaged server has no commit
  await expect(page.getByTestId('worker')).toContainText('Worker container')
})
