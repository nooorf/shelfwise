import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { filtersInWords } from '../session/useConversation'
import { ModeBar } from './ModeBar'

vi.mock('../api/client', () => ({
  getGenres: () => Promise.resolve([
    { name: 'thriller', books: 1204 },
    { name: 'science fiction', books: 310 },
  ]),
}))

const bar = () => {
  const handlers = { onSurprise: vi.fn(), onExplore: vi.fn(), onFilters: vi.fn() }
  render(<ModeBar {...handlers} />)
  return handlers
}

describe('mode bar', () => {
  it('asks for a surprise', async () => {
    const { onSurprise } = bar()
    await userEvent.click(screen.getByRole('button', { name: 'Surprise me' }))
    expect(onSurprise).toHaveBeenCalledOnce()
  })

  it('explores a genre from the catalog list and closes the panel', async () => {
    const { onExplore } = bar()
    const tab = screen.getByRole('button', { name: 'Explore' })
    await userEvent.click(tab)
    expect(tab).toHaveAttribute('aria-expanded', 'true')

    await userEvent.click(await screen.findByRole('button', { name: /science fiction/ }))
    expect(onExplore).toHaveBeenCalledWith('science fiction')
    expect(screen.queryByRole('list', { name: 'Genres' })).not.toBeInTheDocument()
  })

  it('applies only the filters that were filled in', async () => {
    const { onFilters } = bar()
    await userEvent.click(screen.getByRole('button', { name: 'Filters' }))
    const apply = screen.getByRole('button', { name: 'Apply' })
    expect(apply).toBeDisabled()

    await userEvent.type(screen.getByLabelText('At most (pages)'), '300')
    await userEvent.click(screen.getByLabelText('Available now'))
    await userEvent.click(apply)
    expect(onFilters).toHaveBeenCalledWith({
      pages_max: 300, year_from: null, year_to: null, available_now: true,
    })
  })

  it('puts filters in words for the conversation', () => {
    expect(filtersInWords({ pages_max: 300, year_from: 2010, year_to: 2020, available_now: true }))
      .toBe('at most 300 pages, 2010–2020, available now')
    expect(filtersInWords({ year_to: 1950 })).toBe('1950 or earlier')
  })
})
