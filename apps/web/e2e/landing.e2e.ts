// The front door: the featured arc opens a book, a question opens the chat with it asked, and
// the live session is one click away.
import { expect, test } from '@playwright/test'

test('the arc opens a book, a question goes to the chat, and live is a click away', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(/Describe a mood\.\s*Find it on the shelf\./)

  const arc = page.getByRole('region', { name: 'Featured books' })
  const book = arc.getByRole('button').nth(4) // near the middle, never cropped by the screen
  await expect(book).toBeVisible()
  const title = (await book.getAttribute('aria-label'))?.split(' by ')[0] ?? ''
  await book.click()
  await expect(page.getByRole('dialog').getByRole('heading', { level: 2 })).toHaveText(title)
  await page.keyboard.press('Escape')

  await page.getByRole('textbox', { name: 'Ask for a book' }).fill('a short mystery')
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/chat$/) // the question is asked, then dropped from the address
  await expect(page.getByText('a short mystery').first()).toBeVisible()

  await page.goBack()
  await page.getByRole('navigation', { name: 'Pages' }).getByRole('link', { name: 'Live session' }).click()
  await expect(page).toHaveURL(/\/live$/)
  await expect(page.getByRole('button', { name: 'Speak' })).toBeVisible()
})
