// The live page's books: the latest answer's covers fanned on a gentle arc, numbered, because
// a listener says "tell me about the second one". They rise in one after another when an answer
// arrives; pointing lifts one, clicking opens its full record.
import type { CSSProperties } from 'react'

import type { BookResult } from '../api/types'
import { Cover } from '../components/Cover'
import { fanPlace } from './fan'

interface Props {
  books: BookResult[]
  turn: number // the answer's turn, so a new answer replays the rise
  onOpen: (book: BookResult) => void
}

export function BookFan({ books, turn, onOpen }: Props) {
  return (
    <ol className="fan" aria-label="Books" key={turn}>
      {books.map((book, i) => {
        const place = fanPlace(i, books.length)
        const style = {
          '--x': `${place.x}%`,
          '--y': `${place.y}px`,
          '--turn': `${place.turn}deg`,
          '--i': i,
        } as CSSProperties
        return (
          <li key={book.work_id} className="fan-book" style={style}>
            <button type="button" onClick={() => onOpen(book)} aria-label={`${i + 1}. ${book.title}`}>
              <Cover isbn={book.work_key} title={book.title} author={book.authors.join(', ')} />
              <span className="fan-number" aria-hidden="true">
                {i + 1}
              </span>
            </button>
          </li>
        )
      })}
    </ol>
  )
}
