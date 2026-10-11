// One exchange in the chat: what the reader said, then Shelfwise's answer. The answer's books
// show large on the stage beside the chat (CoverFlow); here they are a row of small covers that
// put that answer back on the stage, at the book clicked. Titles and availability come from the
// catalog; only the intro, the "why" lines and the follow-up are the LLM's, and they have
// passed the validator. "Did you mean" and "which filter should I drop" are only offered on
// the latest answer: older ones no longer apply.
import { Cover } from '../components/Cover'
import { PipelineInspector } from '../components/PipelineInspector'
import { Guesses, Offers } from '../components/ResultsShelf'
import { Mark } from '../components/SiteNav'
import type { Exchange } from '../session/store'

interface Props {
  exchange: Exchange
  latest: boolean
  staged: number | null // the book in focus on the stage, when this answer is the one there
  onAsk: (text: string) => void
  onShow: (index: number) => void
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

export function Turn({ exchange: e, latest, staged, onAsk, onShow }: Props) {
  const response = e.response
  const reply = e.reply
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
            <div className={`turn-books ${staged !== null ? 'is-staged' : ''}`}>
              <ul aria-label="Books">
                {books.map((book, i) => (
                  <li key={book.work_id}>
                    <button
                      type="button"
                      onClick={() => onShow(i)}
                      aria-label={`Show ${book.title}`}
                      aria-pressed={staged === i}
                    >
                      <Cover isbn={book.work_key} title={book.title} author={book.authors.join(', ')} />
                    </button>
                  </li>
                ))}
              </ul>
              <span className="turn-books-note">
                {staged !== null ? 'On the stage' : `${books.length} ${books.length === 1 ? 'book' : 'books'}`}
              </span>
            </div>
          )}
          {reply?.follow_up && <p className="bot-follow">{reply.follow_up}</p>}
          {e.cancelled && <p className="bot-note">Stopped.</p>}
          {response && !e.pending && <PipelineInspector response={response} inline />}
        </div>
      </div>
    </li>
  )
}
