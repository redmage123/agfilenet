import { defineConfig } from '@playwright/test'

// The pages under test show real case files, so nothing that captures them
// (screenshots, traces, video) is switched on, and reports stay on the terminal.
export default defineConfig({
  testDir: './e2e',
  // One worker: the app keeps a single-process object database, and some tests write to it.
  workers: 1,
  fullyParallel: false,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: [['list']],
  outputDir: process.env.E2E_OUTPUT_DIR || './test-results',
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://127.0.0.1:8000',
    channel: 'chromium',
    screenshot: 'off',
    trace: 'off',
    video: 'off',
  },
})
