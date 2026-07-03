import { defineConfig, devices } from '@playwright/test'

/**
 * Playwright config for the CSV Insight Agent Phase 1 E2E smoke suite.
 *
 * Precondition: the full stack (FastAPI + static Next.js export) is already
 * running at http://localhost:8001/app/ before this config is invoked — see
 * spec/roadmap.md's Phase 1 gate, steps 1-4. This config does NOT start or
 * stop the server; it assumes an already-running instance (real Gemini API,
 * real SQLite DB — no mocks).
 */
export default defineConfig({
  testDir: './tests/e2e',
  timeout: 90_000,
  expect: {
    timeout: 30_000,
  },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['line']],
  use: {
    baseURL: 'http://localhost:8001/app/',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})
