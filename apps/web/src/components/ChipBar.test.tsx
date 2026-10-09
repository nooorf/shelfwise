import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { Chip } from '../api/types'
import { ChipBar } from './ChipBar'

const chip = (label: string, field: string, strength: string, switchable = true): Chip => ({
  label, field, op: 'lt', value: 300, strength, polarity: 'include', turn: 1, switchable,
})

describe('chip bar', () => {
  it('says which chips are musts and removes one by its button', async () => {
    const onRemove = vi.fn()
    const pages = chip('under 300 pages', 'pages', 'hard')
    render(
      <ChipBar chips={[pages, chip('darker', 'facet.darkness', 'soft')]} onRemove={onRemove} onSwitch={() => {}} />,
    )

    expect(screen.getByText('(must)', { exact: false })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Remove under 300 pages' }))
    expect(onRemove).toHaveBeenCalledWith(pages)
  })

  it('switches a chip between must and preferred, but only a switchable one', async () => {
    const onSwitch = vi.fn()
    const pages = chip('under 300 pages', 'pages', 'hard')
    const darker = chip('darker', 'facet.darkness', 'soft')
    const available = chip('available now', 'available_now', 'hard', false)
    render(<ChipBar chips={[pages, darker, available]} onRemove={() => {}} onSwitch={onSwitch} />)

    const must = screen.getByRole('button', { name: 'Must have under 300 pages' })
    expect(must).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Must have darker' })).toHaveAttribute('aria-pressed', 'false')
    expect(screen.queryByRole('button', { name: 'Must have available now' })).not.toBeInTheDocument()
    await userEvent.click(must)
    expect(onSwitch).toHaveBeenCalledWith(pages)
  })

  it('shows nothing without chips', () => {
    const { container } = render(<ChipBar chips={[]} onRemove={() => {}} onSwitch={() => {}} />)
    expect(container).toBeEmptyDOMElement()
  })
})
