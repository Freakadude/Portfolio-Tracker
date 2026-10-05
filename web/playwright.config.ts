import { defineConfig } from '@playwright/test'

const PORT = 8765
const DB = '../e2e-data/e2e.db'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: { baseURL: `http://127.0.0.1:${PORT}`, trace: 'retain-on-failure' },
  webServer: [
    {
      // Start every run from an empty database: the wizard test needs a fresh install.
      command: 'node web/e2e/reset-db.mjs && uv run folio web',
      cwd: '..',
      url: `http://127.0.0.1:${PORT}/healthz`,
      reuseExistingServer: false,
      // the server's request log (with durations) explains a slow or stuck step in CI
      stdout: process.env.CI ? 'pipe' : 'ignore',
      stderr: 'pipe',
      timeout: 60_000,
      env: {
        FOLIO_SECRET_KEY: 'e2e-only-secret-key-0123456789abcdef0123456789',
        FOLIO_DB_URL: `sqlite:///${DB.replace('../', '')}`,
        FOLIO_PORT: String(PORT),
        FOLIO_HOST: '127.0.0.1',
      },
    },
    {
      // The recorded news feeds, served locally so no real site is contacted.
      command: 'node web/e2e/serve-fixtures.mjs',
      cwd: '..',
      url: 'http://127.0.0.1:8766/ecb_press.xml',
      reuseExistingServer: false,
    },
  ],
})
