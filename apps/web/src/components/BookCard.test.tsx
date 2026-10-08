import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { book } from '../test/fixtures'
import { BookCard } from './BookCard'

describe('book card', () => {
  it('shows catalog facts, availability in words, and the note', () => {
    render(
      <BookCard book={book(1, 'Gone Girl')} position={1} writing={false}
        note={{ work_id: 1, why: 'A marriage with secrets.', source: 'llm' }} />,
    )
    expect(screen.getByRole('article', { name: '1. Gone Girl' })).toBeInTheDocument()
    expect(screen.getByText('Available · Floor 2 · FIC WRI')).toBeInTheDocument()
    expect(screen.getByText('A marriage with secrets.')).toBeInTheDocument()
  })

  it('says a note is coming while the LLM writes', () => {
    render(<BookCard book={book(2)} position={2} writing />)
    expect(screen.getByText('Writing a note…')).toBeInTheDocument()
  })
})
