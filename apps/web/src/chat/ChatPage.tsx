// Text chat (/chat): a conversation that retrieves books, each answer with its own row of
// cards. No microphone and no avatar here (that's /live), and the server never speaks.
// An empty chat is a question with the box under it; once you ask, the thread scrolls and the
// box stays at the bottom with what the search is holding (chips) just above it.
import { AudioLines, Plus, RotateCcw } from 'lucide-react'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'

import type { BookResult, ReplyItem } from '../api/types'
import { Announcer } from '../components/Announcer'
import { BookDrawer } from '../components/BookDrawer'
import { ChipBar } from '../components/ChipBar'
import { Link } from '../components/Link'
import { ModeBar } from '../components/ModeBar'
import { SiteNav } from '../components/SiteNav'
import { EXAMPLES } from '../landing/examples'
import { useSession } from '../session/store'
import { useConversation } from '../session/useConversation'
import '../styles/site.css'
import { Composer } from './Composer'
import { Turn } from './Turn'
import './chat.css'

export function ChatPage() {
  const { ask, undo, removeChip, switchChip, feedback, surprise, explore, filter, cancel, newVisitor } =
    useConversation({ speech: false })
  const status = useSession((s) => s.status)
  const exchanges = useSession((s) => s.exchanges)
  const error = useSession((s) => s.error)
  const [open, setOpen] = useState<{ book: BookResult; note?: ReplyItem } | null>(null)
  const log = useRef<HTMLDivElement>(null)
  const shown = useRef(0) // exchanges already scrolled to

  const latest = exchanges.findLast((e) => e.response)?.response
  const busy = exchanges.some((e) => e.pending)
  const empty = exchanges.length === 0

  // A question asked on the landing page arrives as ?q=; ask it once, then drop it from the
  // address so a reload doesn't ask again.
  useEffect(() => {
    const question = new URLSearchParams(window.location.search).get('q')?.trim()
    if (!question) return
    window.history.replaceState(null, '', window.location.pathname)
    ask(question)
  }, [ask])

  // A new message goes to the top of the thread and its answer grows below it, so the
  // question stays in view while the books arrive (an answer can be taller than the screen).
  useLayoutEffect(() => {
    const count = exchanges.length
    if (count > shown.current) {
      const turns = log.current?.querySelectorAll<HTMLElement>('.turn')
      const last = turns?.[turns.length - 1]
      if (log.current && last) log.current.scrollTop = last.offsetTop - 16
    }
    shown.current = count
  }, [exchanges.length])


  const composer = <Composer onAsk={ask} onCancel={cancel} busy={busy} autoFocus={empty} />
  const modes = <ModeBar onSurprise={surprise} onExplore={explore} onFilters={filter} />

  return (
    <div className="reading-room site chat">
      <Announcer />
      <SiteNav>
        {!empty && (
          <button type="button" className="btn btn-butter" onClick={() => void newVisitor()}>
            <Plus className="size-4" aria-hidden="true" /> New chat
          </button>
        )}
        <Link href="/live" className="btn btn-coral">
          <AudioLines className="size-4" aria-hidden="true" /> Talk instead
        </Link>
      </SiteNav>

      {status === 'offline' && (
        <p role="status" className="chat-offline">
          Can’t reach Shelfwise. Is the API running? Trying again…
        </p>
      )}

      {empty ? (
        <main className="chat-welcome">
          <h1 className="chat-title">What would you like to read?</h1>
          <p className="chat-sub">
            Describe a mood, a topic or a book you loved. Every book I suggest is on these shelves, and
            I’ll tell you which are in today.
          </p>
          {composer}
          <ul className="chat-suggestions" aria-label="Try asking">
            {EXAMPLES.map((example) => (
              <li key={example}>
                <button type="button" onClick={() => ask(example)}>
                  {example}
                </button>
              </li>
            ))}
          </ul>
          <div className="chat-modes">{modes}</div>
        </main>
      ) : (
        <>
          <h1 className="sr-only">Chat with Shelfwise</h1>
          <div ref={log} className="chat-log">
            <ol aria-label="Conversation" className="chat-thread">
              {exchanges.map((exchange) => (
                <Turn
                  key={exchange.key}
                  exchange={exchange}
                  latest={exchange.response === latest}
                  onAsk={ask}
                  onFeedback={feedback}
                  onOpen={(book, note) => setOpen({ book, note })}
                />
              ))}
            </ol>
          </div>
          <footer className="chat-dock">
            <div className="chat-dock-inner">
              {(latest?.chips.length || latest?.can_undo) && (
                <div className="chat-state">
                  <ChipBar chips={latest?.chips ?? []} onRemove={removeChip} onSwitch={switchChip} />
                  {latest?.can_undo && (
                    <button type="button" onClick={undo} className="chat-undo">
                      <RotateCcw className="size-3.5" aria-hidden="true" /> Back to previous search
                    </button>
                  )}
                </div>
              )}
              {error && (
                <p role="alert" className="chat-error">
                  {error}
                </p>
              )}
              {composer}
              {modes}
            </div>
          </footer>
        </>
      )}

      {open && (
        <BookDrawer
          key={open.book.work_id}
          book={open.book}
          note={open.note}
          onClose={() => setOpen(null)}
          onFeedback={feedback}
        />
      )}
    </div>
  )
}
