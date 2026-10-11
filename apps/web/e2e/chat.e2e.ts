// The text chat against the real API: an answer's books take the stage, the arrows step
// through them, the drawer opens, and a chip steers the next answer.
import { expect, test } from '@playwright/test'

test('a typed question puts its books on the stage, and a chip steers the next', async ({ page }) => {
  await page.goto('/chat')
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('What would you like to read?')

  await page.getByRole('textbox', { name: 'Ask for a book' }).fill('thrillers under 300 pages')
  await page.keyboard.press('Enter')

  const conversation = page.getByRole('list', { name: 'Conversation' })
  await expect(conversation.getByText('thrillers under 300 pages')).toBeVisible()
  const stage = page.getByRole('region', { name: 'Books for “thrillers under 300 pages”' })
  const title = stage.getByRole('heading', { level: 2 })
  await expect(title).toBeVisible()
  await expect(page.getByRole('list', { name: 'Active filters' })).toContainText('under 300 pages')

  const first = await title.textContent()
  await stage.getByRole('button', { name: 'Next book' }).click()
  await expect(title).not.toHaveText(first ?? '')
  const second = (await title.textContent()) ?? ''
  await stage.getByRole('button', { name: 'Details and copies' }).click()
  await expect(page.getByRole('dialog').getByRole('heading', { level: 2 })).toHaveText(second)
  await page.keyboard.press('Escape')

  await page.getByRole('button', { name: 'Remove under 300 pages' }).click()
  await expect(conversation.getByText('Remove "under 300 pages"')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Remove under 300 pages' })).toHaveCount(0)
  await expect(conversation.getByRole('list', { name: 'Books' })).toHaveCount(2)
  await expect(page.getByRole('region', { name: 'Books for “Remove "under 300 pages"”' })).toBeVisible()
})

test('a chip switches between must and preferred', async ({ page }) => {
  await page.goto('/chat')
  await page.getByRole('textbox', { name: 'Ask for a book' }).fill('thrillers under 300 pages')
  await page.keyboard.press('Enter')
  const must = page.getByRole('button', { name: 'Must have under 300 pages' })
  await expect(must).toHaveAttribute('aria-pressed', 'true')

  await must.click()

  await expect(must).toHaveAttribute('aria-pressed', 'false')
})

test('explore browses a genre, and the answer says how it searched', async ({ page }) => {
  await page.goto('/chat')
  await page.getByRole('button', { name: 'Explore' }).click()
  await page.getByRole('list', { name: 'Genres' }).getByRole('button', { name: /^horror/ }).click()

  await expect(page.getByRole('list', { name: 'Active filters' })).toContainText('horror')
  await expect(page.getByRole('region', { name: /^Books for/ }).getByRole('heading', { level: 2 })).toBeVisible()
  await page.getByText('How it searched').click()
  await expect(page.getByText('· browse · parser', { exact: false })).toBeVisible()
})

test('surprise me picks books on the shelf now', async ({ page }) => {
  await page.goto('/chat')
  await page.getByRole('button', { name: 'Surprise me' }).click()

  const stage = page.getByRole('region', { name: /^Books for/ })
  await expect(stage.getByRole('heading', { level: 2 })).toBeVisible()
  await expect(stage).toContainText(/available/i)
})

test('works from the keyboard alone', async ({ page }) => {
  await page.goto('/chat')
  await expect(page.getByRole('textbox', { name: 'Ask for a book' })).toBeFocused() // an empty chat
  await page.keyboard.type('thrillers under 300 pages')
  await page.keyboard.press('Enter')
  const remove = page.getByRole('button', { name: 'Remove under 300 pages' })
  await expect(remove).toBeVisible()

  await remove.focus()
  await page.keyboard.press('Enter')

  await expect(remove).toHaveCount(0)
  // Focus lands on the next chip's remove button, or the box, not the page.
  await expect(page.locator('button[data-remove]:focus, #ask:focus')).toHaveCount(1)

  await page.getByRole('region', { name: /^Books for/ }).getByRole('button', { name: /^Open / }).focus()
  await page.keyboard.press('ArrowRight')
  await expect(page.getByRole('region', { name: /^Books for/ })).toContainText('2 of')
})
