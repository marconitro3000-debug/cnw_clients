import { defineConfig } from '@playwright/test'
import { resolve } from 'node:path'

export default defineConfig({
  testDir: './frontend/tests',
  timeout: 30000,
  fullyParallel: false,
  workers: 1,
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:8011',
    browserName: 'chromium',
    viewport: { width: 1440, height: 1000 },
    launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined },
    trace: 'retain-on-failure',
  },
  webServer: {
    command: '.venv\\Scripts\\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8011',
    url: 'http://127.0.0.1:8011/api/health',
    reuseExistingServer: false,
    env: { SCOUT_ENV_PATH: resolve('data', 'browser-test-' + process.pid + '.env'), SCOUT_DATABASE_PATH: resolve('data', 'browser-test-' + process.pid + '.sqlite'), TAVILY_API_KEY: '' },
    timeout: 20000,
  },
})
