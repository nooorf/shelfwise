// The live page's one control: tap to talk, tap again when done (or just stop talking: the
// server hears the pause). While the assistant speaks, a tap interrupts it and listens. A ring
// around the button follows your voice while it listens.
import { Mic, Square } from 'lucide-react'
import { useEffect, useRef } from 'react'

import type { Status } from '../session/store'
import { micLevel } from '../session/useConversation'

const HINTS: Record<Status, string> = {
  starting: 'Connecting…',
  ready: 'Tap and ask for a book',
  listening: 'Listening. I’ll stop when you pause',
  searching: 'Looking through the shelves…',
  writing: 'Finding the words…',
  speaking: 'Tap to interrupt',
  offline: 'Can’t reach Shelfwise. Is the API running?',
}

interface Props {
  status: Status
  listening: boolean
  onPress: () => void
}

export function MicButton({ status, listening, onPress }: Props) {
  const ring = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    const el = ring.current
    if (!listening || !el) return
    let frame = 0
    let shown = 0
    const tick = () => {
      shown += (Math.min(micLevel() * 9, 1) - shown) * 0.3 // eased, so the ring breathes
      el.style.setProperty('--level', shown.toFixed(3))
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => {
      cancelAnimationFrame(frame)
      el.style.setProperty('--level', '0')
    }
  }, [listening])

  return (
    <div className="mic" data-status={status}>
      <button
        type="button"
        className={`mic-button ${listening ? 'is-listening' : ''}`}
        onClick={onPress}
        disabled={status === 'offline' || status === 'starting'}
        aria-pressed={listening}
        aria-label={listening ? 'Stop listening' : 'Speak'}
      >
        <span ref={ring} className="mic-ring" aria-hidden="true" />
        {listening ? (
          <Square className="size-6" fill="currentColor" aria-hidden="true" />
        ) : (
          <Mic className="size-7" aria-hidden="true" />
        )}
      </button>
      <p className="mic-hint" aria-hidden="true">
        {HINTS[status]}
      </p>
    </div>
  )
}
