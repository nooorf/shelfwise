// One exchange in the chat: what the reader said, then Shelfwise's answer with its own books.
// Cards, titles and availability come from the catalog; only the intro, the "why" lines and the
// follow-up are the LLM's, and they have passed the validator. "Did you mean" and "which filter
// should I drop" are only offered on the latest answer: older ones no longer apply.
import type { BookResult, ReplyItem } from '../api/types'
import { BookCard } from '../components/BookCard'
import { PipelineInspector } from '../components/PipelineInspector'
import { Guesses, Offers } from '../components/ResultsShelf'
import { Mark } from '../components/SiteNav'
import type { Exchange } from '../session/store'

interface Props {
  exchange: Exchange
  latest: boolean
  onAsk: (text: string) => void
  onFeedback: (book: BookResult, more: boolean) => void
  onOpen: (book: BookResult, note?: ReplyItem) => void
}

function Thinking() {
  return (
    <p className="bot-thinking">
      Looking through the shelves
      <span className="dots" aria-hidden="true">
        <span />
        <span />
        <span />
      </span>
    </p>
  )
}

export function Turn({ exchange: e, latest, onAsk, onFeedback, onOpen }: Props) {
  const response = e.response
  const reply = e.reply
  const notes = new Map(reply?.items.map((item) => [item.work_id, item]))
  const books = response?.results ?? []
  return (
    <li className="turn">
      {e.said && <p className="turn-user">{e.said}</p>}
      <div className="turn-bot">
        <span className="bot-mark" aria-hidden="true">
          <Mark />
        </span>
        <div className="bot-body">
          {e.pending && !response && <Thinking />}
          {response?.notes.map((note) => (
            <p key={note} className="bot-note">
              {note}
            </p>
          ))}
          {reply?.intro && <p className="bot-intro">{reply.intro}</p>}
          {latest && response && response.guesses.length > 0 && <Guesses guesses={response.guesses} onAsk={onAsk} />}
          {latest && response && response.relaxations.length > 0 && (
            <Offers offers={response.relaxations} onAsk={onAsk} />
          )}
          {books.length > 0 && (
            <ul className="strip" aria-label="Books">
              {books.map((book, i) => (
                <li key={book.work_id}>
                  <BookCard
                    book={book}
                    position={i + 1}
                    note={notes.get(book.work_id)}
                    writing={e.pending && !reply}
                    onFeedback={onFeedback}
                    onOpen={(b) => onOpen(b, notes.get(b.work_id))}
                  />
                </li>
              ))}
            </ul>
          )}
          {reply?.follow_up && <p className="bot-follow">{reply.follow_up}</p>}
          {e.cancelled && <p className="bot-note">Stopped.</p>}
          {response && !e.pending && <PipelineInspector response={response} inline />}
        </div>
      </div>
    </li>
  )
}
