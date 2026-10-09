// Where the talking avatar goes (Phase 6b). Until then a breathing orb shows the assistant's
// state: idle, thinking (searching), speaking (writing its notes). Motion stops for
// prefers-reduced-motion (index.css). The orb is decoration; screen readers hear the turns
// from the announcer, not every state change.
import type { Status } from '../session/store'

const LABELS: Record<Status, string> = {
  starting: 'Connecting',
  ready: 'Ready',
  listening: 'Listening',
  searching: 'Thinking',
  writing: 'Writing',
  speaking: 'Speaking',
  offline: 'Offline: is the API running?',
}

export function AvatarSlot({ status }: { status: Status }) {
  const busy = status === 'searching' || status === 'writing' || status === 'speaking'
  return (
    <div className="flex items-center gap-3">
      <div className="relative size-12 shrink-0" aria-hidden="true">
        <div
          className={`absolute inset-0 rounded-full ${status === 'offline' ? 'bg-quiet-soft' : 'bg-accent'}`}
          style={{ animation: busy ? 'orb-breathe 1.2s ease-in-out infinite' : 'orb-breathe 4s ease-in-out infinite' }}
        />
        {status === 'searching' && (
          <div
            className="absolute -inset-1 rounded-full border-2 border-accent border-t-transparent"
            style={{ animation: 'orb-think 1s linear infinite' }}
          />
        )}
      </div>
      <span className="text-sm text-muted">{LABELS[status]}</span>
    </div>
  )
}
