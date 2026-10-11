// The text chat against the real API: an answer arrives with its own books, a chip steers the
// next one, and a book opens in the drawer.
import { expect, test } from '@playwright/test'

test('a typed question gets an answer with books, and a chip steers the next', async ({ page }) => {
  await page.goto('/chat')
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('What would you like to read?')
  await expect(page.getByRole('button', { name: 'Talk instead' }).or(page.getByRole('link', { name: 'Talk instead' }))).toBeVisible()

  await page.getByRole('textbox', { name: 'Ask for a book' }).fill('thrillers under 300 pages')
  await page.keyboard.press('Enter')

  const conversation = page.getByRole('list', { name: 'Conversation' })
  await expect(conversation.getByText('thrillers under 300 pages')).toBeVisible()
  const books = conversation.getByRole('list', { name: 'Books' }).first()
  await expect(books.getByRole('article').first()).toBeVisible()
  await expect(page.getByRole('list', { name: 'Active filters' })).toContainText('under 300 pages')

  const first = books.getByRole('article').first()
  const title = (await first.getAttribute('aria-label'))?.replace(/^\d+\. /, '') ?? ''
  await first.getByRole('button', { name: title, exact: true }).click()
  await expect(page.getByRole('dialog').getByRole('heading', { level: 2 })).toHaveText(title)
  await page.keyboard.press('Escape')

  await page.getByRole('button', { name: 'Remove under 300 pages' }).click()
  await expect(conversation.getByText('Remove "under 300 pages"')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Remove under 300 pages' })).toHaveCount(0)
  await expect(conversation.getByRole('list', { name: 'Books' })).toHaveCount(2)
})
