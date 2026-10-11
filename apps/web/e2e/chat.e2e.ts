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
