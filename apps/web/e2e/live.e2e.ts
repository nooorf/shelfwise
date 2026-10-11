// The live session against the real API, with Chromium's fake microphone playing the question
// warm-up.ts recorded ("Gothic horror novels, please."). Voice only: no text box on this page.
import { existsSync } from 'node:fs'

import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

import { QUESTION_WAV } from './warm-up.ts'

const answer = (page: Page) => page.getByRole('region', { name: 'Answer' })
const books = (page: Page) => answer(page).getByRole('list', { name: 'Books' }).getByRole('button')

test.beforeEach(async ({ page }) => {
  await page.goto('/live')
})

test('has no text box, and offers the chat instead', async ({ page }) => {
  await expect(page.getByRole('textbox')).toHaveCount(0)
  await expect(page.getByRole('link', { name: 'Type instead' })).toHaveAttribute('href', '/chat')
  await expect(page.getByRole('button', { name: 'Speak' })).toBeEnabled()
})

test('a spoken question is heard, answered aloud with books, and a tap interrupts the voice', async ({ page }) => {
  test.skip(!existsSync(QUESTION_WAV), 'no TTS model to record the question with')
  test.setTimeout(60_000) // the first transcription loads Whisper
  await page.getByRole('button', { name: 'Speak' }).click()

  await expect(answer(page).getByText(/gothic horror/i)).toBeVisible({ timeout: 45_000 })
  await expect(books(page).first()).toBeVisible()
  await expect(books(page).first()).toHaveAccessibleName(/^1\. /) // numbered, for "the first one"
  await expect(page.getByRole('button', { name: 'Speak' })).toHaveAttribute('aria-pressed', 'false')

  await expect(page.getByText('Speaking', { exact: true })).toBeVisible({ timeout: 20_000 })
  await page.getByRole('button', { name: 'Speak' }).click() // barge-in: speech stops at once
  await expect(page.getByText('Speaking', { exact: true })).toHaveCount(0, { timeout: 1_000 })
})

test('a book from the fan opens in the drawer', async ({ page }) => {
  test.skip(!existsSync(QUESTION_WAV), 'no TTS model to record the question with')
  test.setTimeout(60_000)
  await page.getByRole('button', { name: 'Speak' }).click()
  const first = books(page).first()
  await expect(first).toBeVisible({ timeout: 45_000 })
  const title = ((await first.getAttribute('aria-label')) ?? '').replace(/^\d+\. /, '')

  await first.click()
  await expect(page.getByRole('dialog').getByRole('heading', { level: 2 })).toHaveText(title)
})

test('the avatar loads, or falls back to the orb and says why, and can be switched off', async ({ page }) => {
  const toggle = page.getByRole('button', { name: /^Avatar (on|off)$/ })
  await expect(toggle).toHaveAttribute('aria-pressed', 'true')
  // Headless Chromium draws WebGL in software: the avatar may hand over to the orb as too slow.
  await expect(page.locator('[data-avatar="ready"]').or(page.locator('button[title^="Avatar"]'))).toBeVisible({
    timeout: 30_000,
  })

  await toggle.click()

  await expect(toggle).toHaveAttribute('aria-pressed', 'false')
  await expect(page.locator('[data-avatar]')).toHaveCount(0)
  await expect(page.locator('.live-orb')).toBeVisible()
})

test('hands-free answers a spoken question and listens again', async ({ page }) => {
  test.skip(!existsSync(QUESTION_WAV), 'no TTS model to record the question with')
  test.setTimeout(60_000)
  const handsFree = page.getByRole('button', { name: 'Hands-free' })
  await handsFree.click()
  await expect(handsFree).toHaveAttribute('aria-pressed', 'true')

  await expect(answer(page).getByText(/gothic horror/i)).toBeVisible({ timeout: 45_000 })
  await expect(books(page).first()).toBeVisible()
  // No button pressed, yet it's listening for the next question.
  await expect(page.getByRole('button', { name: 'Stop listening' })).toHaveAttribute('aria-pressed', 'true')

  await handsFree.click()
  await expect(page.getByRole('button', { name: 'Speak' })).toHaveAttribute('aria-pressed', 'false')
})
