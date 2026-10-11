// Choices an answer can offer: which filter to drop when nothing matches, and "did you mean"
// when a name didn't match. Each sends a message, so they work the same in chat and live.
import type { Guess, Relaxation } from '../api/types'

export function Offers({ offers, onAsk }: { offers: Relaxation[]; onAsk: (text: string) => void }) {
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

/** "Did you mean": a name that didn't match, and the catalog titles or authors it may be.
 * Choosing one sends the reader's message with the name corrected. */
export function Guesses({ guesses, onAsk }: { guesses: Guess[]; onAsk: (text: string) => void }) {
  return (
    <div className="rounded-md border border-line bg-card p-4">
      <p className="mb-3">Did you mean…</p>
      <div className="flex flex-wrap gap-2">
        {guesses.map((guess) => (
          <button
            key={guess.title}
            type="button"
            onClick={() => onAsk(guess.ask)}
            className="rounded-md border border-accent px-3 py-1.5 text-sm text-accent hover:bg-accent-soft"
          >
            {guess.title}
          </button>
        ))}
      </div>
    </div>
  )
}
