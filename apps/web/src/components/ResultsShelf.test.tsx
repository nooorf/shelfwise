import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { turn } from '../test/fixtures'
import { ResultsShelf } from './ResultsShelf'

describe('results shelf', () => {
  it('offers "did you mean" guesses and asks again with the one chosen', async () => {
    const onAsk = vi.fn()
    const shelf = turn(1, {
      guesses: [
        { title: 'Frankenstein', ask: 'do you have Frankenstein' },
        { title: 'Frankenstein in Baghdad', ask: 'do you have Frankenstein in Baghdad' },
      ],
    })
    render(<ResultsShelf shelf={shelf} reply={null} writing={false} onAsk={onAsk} />)

    expect(screen.getByText('Did you mean…')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Frankenstein' }))
    expect(onAsk).toHaveBeenCalledWith('do you have Frankenstein')
  })

  it('shows no guesses when there are none', () => {
    render(<ResultsShelf shelf={turn(1)} reply={null} writing={false} onAsk={() => {}} />)

    expect(screen.queryByText('Did you mean…')).not.toBeInTheDocument()
  })
})
