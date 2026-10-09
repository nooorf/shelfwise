// The main paths through the app (design doc §22): ask, remove a chip, explore, surprise.
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

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
