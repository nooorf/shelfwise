// The live session (/live): talk to the assistant and it talks back, with a face. Voice only:
// no text box here (that's /chat), one microphone button. On a dark stage, the face on the
// left; on the right, what you said, its answer as a caption, and the books it found fanned
// out and numbered. Answers are always spoken (the server says so when it has no voice model).
import { MessageSquare, UserPlus } from 'lucide-react'
import { useState } from 'react'

import type { BookResult } from '../api/types'
import { ORB_NOTES, readAvatarSetting, writeAvatarSetting } from '../avatar/choice'
import type { OrbReason } from '../avatar/choice'
import { Announcer } from '../components/Announcer'
import { BookDrawer } from '../components/BookDrawer'
import { Link } from '../components/Link'
import { Guesses, Offers } from '../components/ReplyChoices'
import { SiteNav } from '../components/SiteNav'
import { EXAMPLES } from '../landing/examples'
import { useSession } from '../session/store'
import type { Status } from '../session/store'
import { useConversation } from '../session/useConversation'
import '../styles/site.css'
import { BookFan } from './BookFan'
import { LiveFace } from './LiveFace'
import { MicButton } from './MicButton'
import './live.css'

const LABELS: Record<Status, string> = {
  starting: 'Connecting',
  ready: 'Ready',
  listening: 'Listening',
  searching: 'Thinking',
  writing: 'Thinking',
  speaking: 'Speaking',
  offline: 'Offline',
}

export function LivePage() {
  const { ask, listen, toggleHandsFree, newVisitor } = useConversation({ speech: true })
  const status = useSession((s) => (s.playing ? 'speaking' : s.status))
  const listening = useSession((s) => s.listening)
  const handsFree = useSession((s) => s.handsFree)
  const speakOn = useSession((s) => s.speakOn)
  const exchanges = useSession((s) => s.exchanges)
  const shelf = useSession((s) => s.shelf)
  const error = useSession((s) => s.error)
  const [open, setOpen] = useState<BookResult | null>(null)
  const [avatarOn, setAvatarOn] = useState(readAvatarSetting)
  const [orbReason, setOrbReason] = useState<OrbReason | null>(null)

  const last = exchanges.at(-1)
  const answer = exchanges.findLast((e) => e.response)
  const reply = last?.reply ?? (last?.pending ? undefined : answer?.reply)

  return (
    <div className="reading-room site live">
      <Announcer />
      <SiteNav>
        {exchanges.length > 0 && (
          <button type="button" className="btn btn-butter" onClick={() => void newVisitor()}>
            <UserPlus className="size-4" aria-hidden="true" /> New visitor
          </button>
        )}
        <Link href="/chat" className="btn btn-coral">
          <MessageSquare className="size-4" aria-hidden="true" /> Type instead
        </Link>
      </SiteNav>

      <main className="live-stage">
        <h1 className="sr-only">Live session</h1>
        <section className="live-left" aria-label="Assistant">
          {/* keyed by the switch: switching it back on tries the avatar again */}
          <LiveFace key={String(avatarOn)} status={status} wanted={avatarOn} onReason={setOrbReason} />
          <p className="live-status" data-status={status}>
            <span className="live-status-dot" aria-hidden="true" />
            {LABELS[status]}
          </p>
        </section>

        <section className="live-right" aria-label="Answer">
          {!last ? (
            <div className="live-welcome">
              <p className="live-lead">Ask me for a book, out loud.</p>
              <ul className="live-tries" aria-label="Try saying">
                {EXAMPLES.slice(0, 3).map((example) => (
                  <li key={example}>“{example}”</li>
                ))}
              </ul>
            </div>
          ) : (
            <div className="live-caption">
              {last.said && (
                <p className="live-said">
                  <span className="live-said-who">You</span> {last.said}
                </p>
              )}
              {last.fixed?.map((f) => (
                <p key={f.heard} className="live-fixed">
                  Heard “{f.heard}” as {f.catalog}
                </p>
              ))}
              {last.response?.notes.map((note) => (
                <p key={note} className="live-note">
                  {note}
                </p>
              ))}
              {reply?.intro && <p className="live-reply">{reply.intro}</p>}
              {reply?.follow_up && <p className="live-follow">{reply.follow_up}</p>}
              {last.response && last.response.guesses.length > 0 && <Guesses guesses={last.response.guesses} onAsk={ask} />}
              {last.response && last.response.relaxations.length > 0 && (
                <Offers offers={last.response.relaxations} onAsk={ask} />
              )}
            </div>
          )}
          {shelf && shelf.results.length > 0 && <BookFan books={shelf.results} turn={shelf.turn} onOpen={setOpen} />}
        </section>

        <div className="live-controls">
          <span className="live-switches">
            <button type="button" className="live-switch" onClick={toggleHandsFree} aria-pressed={handsFree}>
              Hands-free
            </button>
            <button
              type="button"
              className="live-switch"
              onClick={() => setAvatarOn(writeAvatarSetting(!avatarOn))}
              aria-pressed={avatarOn}
              title={orbReason && orbReason !== 'off' ? ORB_NOTES[orbReason] : undefined}
            >
              {avatarOn ? 'Avatar on' : 'Avatar off'}
            </button>
          </span>
          <MicButton status={status} listening={listening} onPress={listen} />
          <span className="live-controls-side">
            {speakOn === false && <span className="live-warn">No voice: run make download-tts</span>}
          </span>
        </div>
        {error && (
          <p role="alert" className="live-error">
            {error}
          </p>
        )}
      </main>

      {open && <BookDrawer key={open.work_id} book={open} onClose={() => setOpen(null)} />}
    </div>
  )
}
