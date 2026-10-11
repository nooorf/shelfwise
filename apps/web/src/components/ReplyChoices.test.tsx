import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { Guesses, Offers } from './ReplyChoices'

describe('reply choices', () => {
  it('offers "did you mean" guesses and asks again with the one chosen', async () => {
    const onAsk = vi.fn()
    const guesses = [
      { title: 'Frankenstein', ask: 'do you have Frankenstein' },
      { title: 'Frankenstein in Baghdad', ask: 'do you have Frankenstein in Baghdad' },
    ]
    render(<Guesses guesses={guesses} onAsk={onAsk} />)

    expect(screen.getByText('Did you mean…')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Frankenstein' }))
    expect(onAsk).toHaveBeenCalledWith('do you have Frankenstein')
  })

  it('offers which filter to drop, with how many books each gives, or keeping them all', async () => {
    const onAsk = vi.fn()
    render(<Offers offers={[{ drop: 'under 100 pages', count: 3, earliest_due: null }]} onAsk={onAsk} />)

    await userEvent.click(screen.getByRole('button', { name: 'Drop “under 100 pages” · 3 books' }))
    expect(onAsk).toHaveBeenCalledWith('drop under 100 pages')
    await userEvent.click(screen.getByRole('button', { name: 'Keep everything' }))
    expect(onAsk).toHaveBeenLastCalledWith('no thanks')
  })
})
