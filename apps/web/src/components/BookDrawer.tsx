// The full record behind a card (design doc §22.1): opened from a card, closed with Esc, the
// close button or a click outside. The card's facts show at once; the rest loads.
import { ThumbsDown, ThumbsUp, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { getBook } from '../api/client'
import type { BookDetail, BookResult, ReplyItem } from '../api/types'
import { AvailabilityPill } from './AvailabilityPill'
import { copyLine, tagLines } from './bookDetails'
import { Cover } from './Cover'

interface Props {
  book: BookResult
  note?: ReplyItem
  onClose: () => void
  onFeedback?: (book: BookResult, more: boolean) => void
}

export function BookDrawer({ book, note, onClose, onFeedback }: Props) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [detail, setDetail] = useState<BookDetail | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    const element = dialog.current
    if (element && !element.open) {
      if (typeof element.showModal === 'function') element.showModal()
      else element.setAttribute('open', '')
    }
  }, [])

  useEffect(() => {
    let current = true // the shelf keys the drawer by book, so state starts fresh per book
    getBook(book.work_id)
      .then((d) => current && setDetail(d))
      .catch(() => current && setFailed(true))
    return () => {
      current = false
    }
  }, [book.work_id])

  const author = book.authors.join(', ') || 'Unknown author'
  const facts = [book.year, book.pages && `${book.pages} pp`, ...book.genres.slice(0, 3)]
    .filter(Boolean)
    .join(' · ')
  const act = (more: boolean) => {
    onFeedback?.(book, more)
    onClose()
  }

  return (
    <dialog
      ref={dialog}
      aria-labelledby="drawer-title"
      onClose={onClose}
      onClick={(e) => e.target === dialog.current && onClose()} // the backdrop
      className="m-0 ml-auto h-full max-h-none w-full max-w-md overflow-y-auto bg-card p-0 text-ink shadow-xl backdrop:bg-ink/30"
    >
      <div className="flex flex-col gap-4 p-5">
        <div className="flex items-start gap-4">
          <div className="w-24 shrink-0">
            <Cover isbn={book.work_key} title={book.title} author={author} />
          </div>
          <div className="min-w-0 flex-1">
            <h2 id="drawer-title" className="font-serif text-xl leading-tight font-semibold">
              {book.title}
            </h2>
            {book.subtitle && <p className="text-sm text-muted">{book.subtitle}</p>}
            <p className="text-sm">{author}</p>
            {facts && <p className="mt-1 text-xs text-muted">{facts}</p>}
            <div className="mt-2">
              <AvailabilityPill availability={book.availability} />
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-md p-1 text-muted hover:bg-line hover:text-ink"
          >
            <X className="size-5" aria-hidden="true" />
          </button>
        </div>

        {note && <p className="rounded-md bg-accent-soft px-3 py-2 text-sm">{note.why}</p>}

        {failed && <p role="alert" className="text-sm text-out">Couldn&apos;t load the full record.</p>}
        {!detail && !failed && <p className="animate-pulse text-sm text-muted">Loading…</p>}
        {detail && (
          <>
            {detail.description && (
              <section aria-label="Description">
                <p className="text-sm leading-relaxed whitespace-pre-line">{detail.description}</p>
              </section>
            )}
            {tagLines(detail.tags).length > 0 && (
              <section aria-labelledby="drawer-tags">
                <h3 id="drawer-tags" className="mb-1 text-xs font-semibold tracking-wide text-muted uppercase">
                  What it&apos;s like <span className="font-normal normal-case">(a guide, from its description)</span>
                </h3>
                <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-sm">
                  {tagLines(detail.tags).map(([label, value]) => (
                    <div key={label} className="contents">
                      <dt className="text-muted">{label}</dt>
                      <dd>{value}</dd>
                    </div>
                  ))}
                </dl>
              </section>
            )}
            <section aria-labelledby="drawer-copies">
              <h3 id="drawer-copies" className="mb-1 text-xs font-semibold tracking-wide text-muted uppercase">
                Copies
              </h3>
              {detail.copies.length === 0 ? (
                <p className="text-sm text-muted">No copies in the library.</p>
              ) : (
                <ul className="flex flex-col gap-0.5 text-sm">
                  {detail.copies.map((copy, i) => (
                    <li key={i}>{copyLine(copy)}</li>
                  ))}
                </ul>
              )}
            </section>
            {detail.editions.length > 1 && (
              <section aria-labelledby="drawer-editions">
                <h3 id="drawer-editions" className="mb-1 text-xs font-semibold tracking-wide text-muted uppercase">
                  Editions
                </h3>
                <ul className="flex flex-col gap-0.5 text-sm text-muted">
                  {detail.editions.map((e) => (
                    <li key={e.isbn13 ?? `${e.publisher}-${e.year}`}>
                      {[e.publisher, e.year, e.pages && `${e.pages} pp`, e.format].filter(Boolean).join(' · ')}
                      {e.isbn13 && <span className="ml-1 text-xs">ISBN {e.isbn13}</span>}
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </>
        )}

        {onFeedback && (
          <div className="flex gap-2 border-t border-line pt-3">
            <button
              type="button"
              onClick={() => act(true)}
              className="inline-flex items-center gap-1.5 rounded-md border border-accent px-3 py-1.5 text-sm text-accent hover:bg-accent-soft"
            >
              <ThumbsUp className="size-4" aria-hidden="true" /> More like this
            </button>
            <button
              type="button"
              onClick={() => act(false)}
              className="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm text-muted hover:bg-line hover:text-ink"
            >
              <ThumbsDown className="size-4" aria-hidden="true" /> Less like this
            </button>
          </div>
        )}
      </div>
    </dialog>
  )
}
