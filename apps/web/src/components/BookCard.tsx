// Titles, authors and availability come from the catalog; only the "why" line is the LLM's,
// and it has passed the validator (design doc §18.2).
import type { BookResult, ReplyItem } from '../api/types'
import { AvailabilityPill } from './AvailabilityPill'
import { Cover } from './Cover'

interface Props {
  book: BookResult
  position: number
  note?: ReplyItem
  writing: boolean
}

export function BookCard({ book, position, note, writing }: Props) {
  const author = book.authors.join(', ') || 'Unknown author'
  const facts = [book.year, book.pages && `${book.pages} pp`].filter(Boolean).join(' · ')
  return (
    <article
      aria-label={`${position}. ${book.title}`}
      className="flex flex-col gap-2 rounded-md border border-line bg-card p-3 shadow-sm"
    >
      <div className="relative">
        <Cover isbn={book.work_key} title={book.title} author={author} />
        <span className="absolute top-1.5 left-1.5 rounded-full bg-card/90 px-1.5 text-xs font-semibold text-muted">
          {position}
        </span>
      </div>
      <div>
        <h3 className="font-serif text-base leading-tight font-semibold">{book.title}</h3>
        <p className="text-sm text-muted">{author}</p>
        {facts && <p className="text-xs text-muted">{facts}</p>}
      </div>
      <AvailabilityPill availability={book.availability} />
      {note ? (
        <p className="text-sm leading-snug" title={note.source === 'template' ? 'From the catalog record' : undefined}>
          {note.why}
        </p>
      ) : (
        writing && <p className="animate-pulse text-sm text-muted">Writing a note…</p>
      )}
    </article>
  )
}
