import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { BookDetail } from '../api/types'
import { book } from '../test/fixtures'
import { BookDrawer } from './BookDrawer'

const gone = book(1, 'Gone Girl')
const detail: BookDetail = {
  ...gone,
  description: 'A marriage gone wrong.',
  tags: { darkness: 3 },
  editions: [{ isbn13: gone.work_key, publisher: 'Crown', year: 2012, pages: 432, format: null }],
  copies: [{ branch: 'Main', floor: '2', call_number: 'FIC FLY', status: 'available', due_date: null }],
}

afterEach(() => vi.unstubAllGlobals())

describe('book drawer', () => {
  it('shows the card at once, then the full record, and closes', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(detail))))
    const onClose = vi.fn()
    render(<BookDrawer book={gone} onClose={onClose} />)

    expect(screen.getByRole('heading', { name: 'Gone Girl' })).toBeInTheDocument()
    expect(await screen.findByText('A marriage gone wrong.')).toBeInTheDocument()
    expect(screen.getByText('Very dark')).toBeInTheDocument()
    expect(screen.getByText('On the shelf — Main · Floor 2 · FIC FLY')).toBeInTheDocument()
    expect(fetch).toHaveBeenCalledWith('/api/v1/books/1')

    await userEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(onClose).toHaveBeenCalled()
  })

  it('says so when the record cannot be loaded', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 500 })))
    render(<BookDrawer book={gone} onClose={() => {}} />)
    expect(await screen.findByRole('alert')).toHaveTextContent("Couldn't load the full record.")
  })
})
