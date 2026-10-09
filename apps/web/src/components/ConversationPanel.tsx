import type { Exchange } from '../session/store'

export function ConversationPanel({ exchanges }: { exchanges: Exchange[] }) {
  return (
    <ol aria-label="Conversation" className="flex flex-col gap-3 text-sm">
      {exchanges.map((e) => (
        <li key={e.key} className="flex flex-col gap-1.5">
          {e.said && (
            <p className="self-end rounded-lg bg-accent-soft px-3 py-2 text-ink">{e.said}</p>
          )}
          <div className="flex flex-col gap-1 text-ink">
            {e.response?.notes.map((note) => <p key={note}>{note}</p>)}
            {e.reply?.intro && <p className="font-serif">{e.reply.intro}</p>}
            {e.cancelled && <p className="text-muted italic">(stopped)</p>}
            {e.pending && !e.response && <p className="animate-pulse text-muted">Looking…</p>}
          </div>
        </li>
      ))}
    </ol>
  )
}
