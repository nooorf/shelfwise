// The main paths through the app (design doc §22): ask, remove a chip, explore, surprise.
import { existsSync } from 'node:fs'

import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

import { QUESTION_WAV } from './warm-up.ts'

async function ask(page: Page, text: string) {
  await page.getByLabel('Ask about the collection').fill(text)
  await page.getByRole('button', { name: 'Ask', exact: true }).click()
}

const cards = (page: Page) => page.getByRole('region', { name: 'Books' }).getByRole('article')
const chips = (page: Page) => page.getByRole('list', { name: 'Active filters' })

test.beforeEach(async ({ page }) => {
  await page.goto('/')
})

test('a typed question shows book cards', async ({ page }) => {
  await ask(page, 'psychological thrillers')

  await expect(cards(page).first()).toBeVisible()
  await expect(page.getByRole('list', { name: 'Conversation' })).toContainText('psychological thrillers')
})

test('removing a chip searches again without it', async ({ page }) => {
  await ask(page, 'thrillers under 300 pages')
  await expect(chips(page)).toContainText('under 300 pages')
  await expect(cards(page).first()).toBeVisible()

  await page.getByRole('button', { name: 'Remove under 300 pages' }).click()

  await expect(page.getByRole('list', { name: 'Conversation' })).toContainText('Remove "under 300 pages"')
  await expect(page.getByRole('button', { name: 'Remove under 300 pages' })).toHaveCount(0)
  await expect(cards(page).first()).toBeVisible()
})

test('a chip switches between must and preferred', async ({ page }) => {
  await ask(page, 'thrillers under 300 pages')
  const must = page.getByRole('button', { name: 'Must have under 300 pages' })
  await expect(must).toHaveAttribute('aria-pressed', 'true')

  await must.click()

  await expect(must).toHaveAttribute('aria-pressed', 'false')
})

test('explore browses a genre', async ({ page }) => {
  await page.getByRole('button', { name: 'Explore' }).click()
  await page.getByRole('list', { name: 'Genres' }).getByRole('button', { name: /^horror/ }).click()

  await expect(chips(page)).toContainText('horror')
  await expect(cards(page).first()).toBeVisible()
  await page.getByText('Pipeline inspector').click()
  await expect(page.getByText('· browse · parser', { exact: false })).toBeVisible()
})

test('surprise me picks books on the shelf now', async ({ page }) => {
  await page.getByRole('button', { name: 'Surprise me' }).click()

  await expect(cards(page).first()).toBeVisible()
  await expect(cards(page).first()).toContainText(/available/i)
})

test('works from the keyboard alone', async ({ page }) => {
  await page.keyboard.press('Tab')
  await expect(page.getByRole('link', { name: 'Skip to results' })).toBeFocused()
  await page.getByLabel('Ask about the collection').focus()
  await page.keyboard.type('thrillers under 300 pages')
  await page.keyboard.press('Enter')
  const remove = page.getByRole('button', { name: 'Remove under 300 pages' })
  await expect(remove).toBeVisible()

  await remove.focus()
  await page.keyboard.press('Enter')

  await expect(remove).toHaveCount(0)
  // Focus lands on the next chip's remove button, or the search box, not the page.
  await expect(page.locator('button[data-remove]:focus, #ask:focus')).toHaveCount(1)
})

test('the bench page shows every system and the parser', async ({ page }) => {
  await page.goto('/bench')

  const board = page.getByRole('table').first()
  await expect(board.getByRole('rowheader', { name: /parsed_hybrid/ })).toBeVisible()
  await expect(page.getByRole('img', { name: /nDCG@10 against p95 latency/ })).toBeVisible()
  await expect(page.getByText('Intent accuracy')).toBeVisible()
})

test('read aloud speaks the reply and a new question interrupts it', async ({ page }) => {
  const toggle = page.getByRole('button', { name: 'Read aloud' })
  await toggle.click()
  await expect(toggle).toHaveAttribute('aria-pressed', 'true')

  await ask(page, 'gothic horror')
  await expect(page.getByText('Speaking', { exact: true })).toBeVisible({ timeout: 20_000 })

  await ask(page, 'cozy mysteries') // barge-in: speech stops at once
  await expect(page.getByText('Speaking', { exact: true })).toHaveCount(0, { timeout: 1_000 })
})

test('a spoken question is heard, written down and answered', async ({ page }) => {
  test.skip(!existsSync(QUESTION_WAV), 'no TTS model to record the question with')
  test.setTimeout(60_000) // the first transcription loads Whisper
  await page.getByRole('button', { name: 'Speak' }).click()

  const heard = page.getByRole('list', { name: 'Conversation' }).getByText(/gothic horror/i)
  await expect(heard).toBeVisible({ timeout: 45_000 })
  await expect(cards(page).first()).toBeVisible()
  await expect(page.getByRole('button', { name: 'Speak' })).toHaveAttribute('aria-pressed', 'false')
})

test('the avatar loads, or falls back to the orb, and can be switched off', async ({ page }) => {
  const toggle = page.getByRole('button', { name: /^Avatar (on|off)$/ })
  await expect(toggle).toHaveAttribute('aria-pressed', 'true')
  // Headless Chromium draws WebGL in software: the avatar may hand over to the orb as too slow.
  await expect(page.locator('[data-avatar="ready"]').or(page.getByText('Ready', { exact: true }))).toBeVisible({
    timeout: 30_000,
  })

  await toggle.click()

  await expect(toggle).toHaveAttribute('aria-pressed', 'false')
  await expect(page.locator('[data-avatar]')).toHaveCount(0)
})
