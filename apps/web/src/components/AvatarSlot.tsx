// Where the talking avatar goes (Phase 6b). Until then a breathing orb shows the assistant's
// state: idle, thinking (searching), speaking (writing its notes). Motion stops for
// prefers-reduced-motion (index.css).
import type { Status } from '../session/store'

const LABELS: Record<Status, string> = {
  starting: 'Connecting',
  ready: 'Ready',
  searching: 'Thinking',
  writing: 'Writing',
  offline: 'Offline: is the API running?',
}

export function AvatarSlot({ status }: { status: Status }) {
  const busy = status === 'searching' || status === 'writing'
  return (
    <div className="flex items-center gap-3" role="status" aria-label={LABELS[status]}>
      <div className="relative size-12 shrink-0">
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
