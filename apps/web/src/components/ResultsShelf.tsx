import { useState } from 'react'

import type { BookResult, Relaxation, Reply, TurnResponse } from '../api/types'
import { BookCard } from './BookCard'
import { BookDrawer } from './BookDrawer'

interface Props {
  shelf: TurnResponse | null
  reply: Reply | null
  writing: boolean
  onAsk: (text: string) => void
  onFeedback?: (book: BookResult, more: boolean) => void
}

function Offers({ offers, onAsk }: { offers: Relaxation[]; onAsk: (text: string) => void }) {
  return (
    <div className="rounded-md border border-line bg-card p-4">
      <p className="mb-3">Nothing matches everything. Which should I drop?</p>
      <div className="flex flex-wrap gap-2">
        {offers.map((offer) => (
          <button
            key={offer.drop}
            type="button"
            onClick={() => onAsk(`drop ${offer.drop}`)}
            className="rounded-md border border-accent px-3 py-1.5 text-sm text-accent hover:bg-accent-soft"
          >
            Drop “{offer.drop}” · {offer.count} {offer.count === 1 ? 'book' : 'books'}
          </button>
        ))}
        <button
          type="button"
          onClick={() => onAsk('no thanks')}
          className="rounded-md px-3 py-1.5 text-sm text-muted hover:text-ink"
        >
          Keep everything
        </button>
      </div>
    </div>
  )
}

export function ResultsShelf({ shelf, reply, writing, onAsk, onFeedback }: Props) {
  const [openId, setOpenId] = useState<number | null>(null)
  if (!shelf) {
    return (
      <div className="grid h-full place-items-center p-8 text-center text-muted">
        <p className="max-w-sm font-serif text-lg">
          Tell me what you feel like reading: a mood, a topic, a book you loved, or a title.
        </p>
      </div>
    )
  }
  const notes = new Map(reply?.items.map((item) => [item.work_id, item]))
  const open = shelf.results.find((b) => b.work_id === openId)
  return (
    <section aria-label="Books" className="flex flex-col gap-4">
      {reply?.intro && <p className="font-serif text-lg">{reply.intro}</p>}
      {shelf.relaxations.length > 0 && <Offers offers={shelf.relaxations} onAsk={onAsk} />}
      <div className="grid grid-cols-[repeat(auto-fill,minmax(10.5rem,1fr))] gap-4">
        {shelf.results.map((book, i) => (
          <BookCard
            key={book.work_id}
            book={book}
            position={i + 1}
            note={notes.get(book.work_id)}
            writing={writing && !reply}
            onFeedback={onFeedback}
            onOpen={(b) => setOpenId(b.work_id)}
          />
        ))}
      </div>
      {reply?.follow_up && <p className="text-muted italic">{reply.follow_up}</p>}
      {open && (
        <BookDrawer
          key={open.work_id}
          book={open}
          note={notes.get(open.work_id)}
          onClose={() => setOpenId(null)}
          onFeedback={onFeedback}
        />
      )}
    </section>
  )
}
