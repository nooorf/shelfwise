// The benchmark dashboard, from the newest dev-split reports.
import { expect, test } from '@playwright/test'

test('the bench page shows every system and the parser', async ({ page }) => {
  await page.goto('/bench')

  const board = page.getByRole('table').first()
  await expect(board.getByRole('rowheader', { name: /parsed_hybrid/ })).toBeVisible()
  await expect(page.getByRole('img', { name: /nDCG@10 against p95 latency/ })).toBeVisible()
  await expect(page.getByText('Intent accuracy')).toBeVisible()
})
