import { defineConfig } from '@playwright/test'

const PORT = 8765
const DB = '../e2e-data/e2e.db'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: { baseURL: `http://127.0.0.1:${PORT}`, trace: 'retain-on-failure' },
  webServer: {
    // Start every run from an empty database: the wizard test needs a fresh install.
    command: 'node web/e2e/reset-db.mjs && uv run folio web',
    cwd: '..',
    url: `http://127.0.0.1:${PORT}/healthz`,
    reuseExistingServer: false,
    timeout: 60_000,
    env: {
      FOLIO_SECRET_KEY: 'e2e-only-secret-key-0123456789abcdef0123456789',
      FOLIO_DB_URL: `sqlite:///${DB.replace('../', '')}`,
      FOLIO_PORT: String(PORT),
      FOLIO_HOST: '127.0.0.1',
    },
  },
})
