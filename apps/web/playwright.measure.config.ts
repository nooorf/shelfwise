// The voice measurements (`make measure`, e2e/measure.voice.ts), apart from the browser tests:
// a headed browser (the avatar needs the GPU) and the API as configured, so with `make llm`
// running the parse and the narration are the real ones. Servers already running are reused.
import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  testMatch: 'measure.voice.ts',
  globalSetup: './e2e/warm-up.ts',
  timeout: 0,
  retries: 0,
  reporter: [['list']],
  use: {
    ...devices['Desktop Chrome'],
    baseURL: 'http://localhost:5173',
    headless: false,
    launchOptions: { args: ['--autoplay-policy=no-user-gesture-required', '--use-fake-ui-for-media-stream'] },
  },
  webServer: [
    {
      command: 'uv run uvicorn shelfwise.api.main:app --port 8000',
      cwd: '../..',
      env: { HF_HUB_OFFLINE: '1' },
      url: 'http://localhost:8000/api/v1/health',
      reuseExistingServer: true,
      timeout: 180_000,
    },
    {
      command: 'npm run dev -- --port 5173 --strictPort',
      url: 'http://localhost:5173',
      reuseExistingServer: true,
      timeout: 60_000,
    },
  ],
})
