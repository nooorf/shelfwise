import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { Chip } from '../api/types'
import { ChipBar } from './ChipBar'

const chip = (label: string, field: string, strength: string): Chip => ({
  label, field, op: 'lt', value: 300, strength, polarity: 'include', turn: 1,
})

describe('chip bar', () => {
  it('says which chips are musts and removes one by its button', async () => {
    const onRemove = vi.fn()
    const pages = chip('under 300 pages', 'pages', 'hard')
    render(<ChipBar chips={[pages, chip('darker', 'facet.darkness', 'soft')]} onRemove={onRemove} />)

    expect(screen.getByText('(must)', { exact: false })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Remove under 300 pages' }))
    expect(onRemove).toHaveBeenCalledWith(pages)
  })

  it('shows nothing without chips', () => {
    const { container } = render(<ChipBar chips={[]} onRemove={() => {}} />)
    expect(container).toBeEmptyDOMElement()
  })
})
