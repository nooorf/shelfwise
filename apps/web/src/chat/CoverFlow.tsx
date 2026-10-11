// The chat's stage: one answer's books as a Cover Flow. The book in focus faces the reader
// with its details underneath (catalog facts, live availability, the validated "why"); the
// others stand angled behind it on both sides. Arrows, the arrow keys, a click on a side book
// or a dot bring another forward; a click on the book in focus opens the full record.
import { ChevronLeft, ChevronRight, ThumbsDown, ThumbsUp } from 'lucide-react'
import type { KeyboardEvent } from 'react'

import type { BookResult, ReplyItem } from '../api/types'
import { AvailabilityPill } from '../components/AvailabilityPill'
import { Cover } from '../components/Cover'
import { placement } from './flow'

interface Props {
  question: string
  books: BookResult[]
  notes: Map<number, ReplyItem>
  writing: boolean
  focus: number
  onFocus: (index: number) => void
  onOpen: (book: BookResult) => void
  onFeedback: (book: BookResult, more: boolean) => void
}

export function CoverFlow({ question, books, notes, writing, focus, onFocus, onOpen, onFeedback }: Props) {
  const book = books[focus]
  if (!book) return null
  const note = notes.get(book.work_id)
  const author = book.authors.join(', ') || 'Unknown author'
  const facts = [book.year, book.pages && `${book.pages} pages`, book.genres[0]].filter(Boolean).join(' · ')
  const go = (index: number) => onFocus(Math.max(0, Math.min(books.length - 1, index)))

  function onKeyDown(e: KeyboardEvent) {
    if (e.key === 'ArrowLeft') go(focus - 1)
    else if (e.key === 'ArrowRight') go(focus + 1)
    else return
    e.preventDefault()
  }

  return (
    <section
      className="flow"
      aria-roledescription="carousel"
      aria-label={`Books for “${question}”`}
      onKeyDown={onKeyDown}
    >
      <p className="flow-eyebrow">
        <span className="flow-question">For “{question}”</span>
        <span className="flow-count">
          {focus + 1} of {books.length}
        </span>
      </p>

      <div className="flow-track">
        {books.map((b, i) => (
          <button
            key={b.work_id}
            type="button"
            className={`flow-book ${i === focus ? 'is-focus' : ''}`}
            style={placement(i - focus)}
            onClick={() => (i === focus ? onOpen(b) : go(i))}
            aria-label={i === focus ? `Open ${b.title}` : `Show ${b.title}`}
            tabIndex={i === focus ? 0 : -1}
          >
            <Cover isbn={b.work_key} title={b.title} author={b.authors.join(', ')} />
          </button>
        ))}
        <button type="button" className="flow-arrow is-prev" onClick={() => go(focus - 1)} disabled={focus === 0} aria-label="Previous book">
          <ChevronLeft className="size-5" aria-hidden="true" />
        </button>
        <button
          type="button"
          className="flow-arrow is-next"
          onClick={() => go(focus + 1)}
          disabled={focus === books.length - 1}
          aria-label="Next book"
        >
          <ChevronRight className="size-5" aria-hidden="true" />
        </button>
      </div>

      <div className="flow-details" aria-live="polite">
        <h2 className="flow-title">{book.title}</h2>
        <p className="flow-byline">
          {author}
          {facts && <span> · {facts}</span>}
        </p>
        <AvailabilityPill availability={book.availability} />
        {note ? (
          <p className="flow-why">{note.why}</p>
        ) : (
          writing && <p className="flow-why is-writing">Writing a note…</p>
        )}
        <div className="flow-actions">
          <button type="button" className="flow-action is-primary" onClick={() => onOpen(book)}>
            Details and copies
          </button>
          <button type="button" className="flow-action" onClick={() => onFeedback(book, true)} aria-label={`More like ${book.title}`}>
            <ThumbsUp className="size-3.5" aria-hidden="true" /> More like this
          </button>
          <button type="button" className="flow-action" onClick={() => onFeedback(book, false)} aria-label={`Less like ${book.title}`}>
            <ThumbsDown className="size-3.5" aria-hidden="true" /> Less
          </button>
        </div>
      </div>

      <div className="flow-dots" role="group" aria-label="Choose a book">
        {books.map((b, i) => (
          <button
            key={b.work_id}
            type="button"
            className={`flow-dot ${i === focus ? 'is-on' : ''}`}
            onClick={() => go(i)}
            aria-label={`Book ${i + 1}: ${b.title}`}
            aria-current={i === focus || undefined}
          />
        ))}
      </div>
    </section>
  )
}
