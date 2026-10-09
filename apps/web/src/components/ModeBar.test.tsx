import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { ModeBar } from './ModeBar'

describe('mode bar', () => {
  it('asks for a surprise', async () => {
    const onSurprise = vi.fn()
    render(<ModeBar onSurprise={onSurprise} />)

    await userEvent.click(screen.getByRole('button', { name: 'Surprise me' }))
    expect(onSurprise).toHaveBeenCalledOnce()
  })
})
