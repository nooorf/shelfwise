// "Read aloud": replies are spoken as well as shown (design doc §21). The text stays on
// screen either way: it is the caption.
import { Volume2, VolumeX } from 'lucide-react'

interface SpeakToggleProps {
  wanted: boolean
  on: boolean | null // the server's answer: false when it has no speech model
  onToggle: () => void
}

export function SpeakToggle({ wanted, on, onToggle }: SpeakToggleProps) {
  const unavailable = wanted && on === false
  return (
    <button
      type="button"
      aria-pressed={wanted}
      onClick={onToggle}
      title={unavailable ? 'Speech isn’t set up on the server (make download-tts)' : undefined}
      className={`inline-flex items-center gap-1.5 text-sm hover:text-ink ${wanted ? 'text-accent' : 'text-muted'}`}
    >
      {wanted ? <Volume2 className="size-4" aria-hidden="true" /> : <VolumeX className="size-4" aria-hidden="true" />}
      Read aloud
      {unavailable && <span className="text-xs text-out">(unavailable)</span>}
    </button>
  )
}
