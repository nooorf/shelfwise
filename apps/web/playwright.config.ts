// End-to-end tests in a real browser against the real API and database (`make up` first, with
// the catalog loaded). The API runs with the rules parser, so no LLM is needed and answers are
// deterministic; servers already running (`make api`, `make web`) are reused.
import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  testMatch: '*.e2e.ts', // not *.test.ts: those are Vitest's
  globalSetup: './e2e/warm-up.ts',
  timeout: 30_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: 'uv run uvicorn shelfwise.api.main:app --port 8000',
      cwd: '../..',
      env: { SHELFWISE_QUERY_PARSER: 'rules', HF_HUB_OFFLINE: '1' }, // the models are cached
      url: 'http://localhost:8000/api/v1/health',
      reuseExistingServer: true,
      timeout: 180_000, // loads the search indexes and the embedding model
    },
    {
      command: 'npm run dev -- --port 5173 --strictPort',
      url: 'http://localhost:5173',
      reuseExistingServer: true,
      timeout: 60_000,
    },
  ],
})
