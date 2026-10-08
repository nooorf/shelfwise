import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ErrorBoundary } from './ErrorBoundary'

function Broken(): never {
  throw new Error('boom')
}

afterEach(() => vi.restoreAllMocks())

describe('error boundary', () => {
  it('shows its children when nothing breaks', () => {
    render(<ErrorBoundary><p>Shelf</p></ErrorBoundary>)
    expect(screen.getByText('Shelf')).toBeInTheDocument()
  })

  it('replaces a broken screen with a way back', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    render(<ErrorBoundary><Broken /></ErrorBoundary>)
    expect(screen.getByRole('alert')).toHaveTextContent('Something went wrong on this screen.')
    expect(screen.getByRole('button', { name: 'Start over' })).toBeInTheDocument()
  })
})
