// The ways in besides asking (design doc §22.1, §22.3). None of them calls the LLM: each builds
// the request straight from what was tapped.
import { Shuffle } from 'lucide-react'

export function ModeBar({ onSurprise }: { onSurprise: () => void }) {
  return (
    <nav aria-label="Ways to search" className="flex flex-wrap items-center gap-1.5 text-sm">
      <button
        type="button"
        onClick={onSurprise}
        className="inline-flex items-center gap-1.5 rounded-full border border-line px-3 py-1 text-ink hover:border-accent hover:text-accent focus-visible:outline-2 focus-visible:outline-accent"
      >
        <Shuffle className="size-3.5" aria-hidden="true" /> Surprise me
      </button>
    </nav>
  )
}
