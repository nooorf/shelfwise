import { ArrowUp } from 'lucide-react'
import { useState } from 'react'

export function SearchBar({ onAsk, onCancel }: { onAsk: (text: string) => void; onCancel: () => void }) {
  const [text, setText] = useState('')
  return (
    <form
      className="flex w-full items-center gap-2 rounded-full border border-line bg-card px-4 py-1.5 shadow-sm focus-within:border-accent focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-accent"
      onSubmit={(event) => {
        event.preventDefault()
        onAsk(text)
        setText('')
      }}
    >
      <label htmlFor="ask" className="sr-only">
        Ask about the collection
      </label>
      <input
        id="ask"
        value={text}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={(event) => event.key === 'Escape' && onCancel()}
        placeholder="Ask anything about the collection…"
        autoComplete="off"
        maxLength={500}
        className="min-w-0 flex-1 bg-transparent py-1.5 outline-none placeholder:text-muted"
      />
      <button
        type="submit"
        aria-label="Ask"
        disabled={!text.trim()}
        className="grid size-8 place-items-center rounded-full bg-accent text-card disabled:opacity-40"
      >
        <ArrowUp className="size-4" aria-hidden="true" />
      </button>
    </form>
  )
}
