import path from 'node:path';
import dotenv from 'dotenv';
import { defineConfig, devices } from '@playwright/test';

// UI tests run on UAT only (PRD FR-09). Values come from ui-tests/.env.uat
// locally, or from environment variables in CI.
const env = (process.env.POOLBRAIN_ENV ?? 'uat').toLowerCase();
if (env !== 'uat') {
  throw new Error(`UI tests run on UAT only; POOLBRAIN_ENV is '${env}'.`);
}
if (process.env.CI !== 'true') {
  dotenv.config({ path: path.resolve(__dirname, '.env.uat'), quiet: true });
}

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: [
    ['list'],
    ['html', { outputFolder: 'reports/html', open: 'never' }],
    ['allure-playwright', { resultsDir: 'reports/allure-results' }],
  ],
  outputDir: 'test-results',
  use: {
    baseURL: process.env.BASE_URL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
