import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { FeaturedBook } from '../api/types'
import { book } from '../test/fixtures'
import { LandingPage } from './LandingPage'

const featured: FeaturedBook[] = [
  { ...book(1, 'Wicked'), cover_id: 101 },
  { ...book(2, 'The Name of the Wind', 'borrowed'), cover_id: 102 },
]

afterEach(() => {
  vi.unstubAllGlobals()
  window.history.pushState(null, '', '/')
})

function stubApi() {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) =>
      url === '/api/v1/featured'
        ? new Response(JSON.stringify(featured))
        : new Response('', { status: 404 }),
    ),
  )
}

describe('landing page', () => {
  it('says what it is and offers the ways in', () => {
    stubApi()
    render(<LandingPage />)

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Describe a mood.Find it on the shelf.')
    expect(screen.getByRole('link', { name: 'Shelfwise' })).toHaveAttribute('href', '/')
    const pages = screen.getByRole('navigation', { name: 'Pages' })
    expect(within(pages).getByRole('link', { name: 'Live session' })).toHaveAttribute('href', '/live')
    expect(within(pages).getByRole('link', { name: 'Benchmarks' })).toHaveAttribute('href', '/bench')
  })

  it('asks a question by opening the chat with it', async () => {
    stubApi()
    render(<LandingPage />)

    await userEvent.type(screen.getByRole('textbox', { name: 'Ask for a book' }), 'a short mystery{Enter}')
    expect(window.location.pathname).toBe('/chat')
    expect(new URLSearchParams(window.location.search).get('q')).toBe('a short mystery')
  })

  it('stays put when asked nothing', async () => {
    stubApi()
    render(<LandingPage />)

    await userEvent.click(screen.getByRole('button', { name: 'Ask' }))
    expect(window.location.pathname).toBe('/')
    expect(screen.getByRole('textbox', { name: 'Ask for a book' })).toHaveFocus()
  })

  it('shows each featured book, with its cover, and opens it', async () => {
    stubApi()
    render(<LandingPage />)
    const arc = screen.getByRole('region', { name: 'Featured books' })

    const books = await within(arc).findAllByRole('button')
    expect(books.map((b) => b.getAttribute('aria-label'))).toEqual([
      'Wicked by A. Writer',
      'The Name of the Wind by A. Writer',
    ])
    expect(arc.querySelector('img')).toHaveAttribute('src', 'https://covers.openlibrary.org/b/id/101-M.jpg')

    await userEvent.click(books[0])
    expect(screen.getByRole('heading', { name: 'Wicked', level: 2 })).toBeInTheDocument()
  })

  it('names the book being pointed at, and whether it is in', async () => {
    stubApi()
    render(<LandingPage />)
    const books = await within(screen.getByRole('region', { name: 'Featured books' })).findAllByRole('button')

    await userEvent.hover(books[1])
    expect(screen.getByText('The Name of the Wind', { selector: '.arc-caption-title' })).toBeInTheDocument()
    expect(screen.getByText(/^Due back/)).toBeInTheDocument()
    await userEvent.unhover(books[1])
    expect(screen.queryByText('The Name of the Wind', { selector: '.arc-caption-title' })).toBeNull()
  })

  it('still works without the featured books', () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 500 })))
    render(<LandingPage />)
    expect(screen.getByRole('textbox', { name: 'Ask for a book' })).toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: 'Featured books' })).queryAllByRole('button')).toEqual([])
  })
})
