// Layout (design doc §22.1): the results shelf is the main surface; the conversation is a
// narrow column that steers it; the active constraints are always visible as chips.
import { RotateCcw, UserPlus } from 'lucide-react'
import { useEffect } from 'react'

import { Announcer } from './components/Announcer'
import { AvatarSlot } from './components/AvatarSlot'
import { ChipBar } from './components/ChipBar'
import { ConversationPanel } from './components/ConversationPanel'
import { ModeBar } from './components/ModeBar'
import { PipelineInspector } from './components/PipelineInspector'
import { ResultsShelf } from './components/ResultsShelf'
import { SearchBar } from './components/SearchBar'
import { HandsFreeToggle, SpeakToggle } from './components/SpeakToggle'
import { useConversation } from './session/useConversation'
import { useSession } from './session/store'

export default function App() {
  const {
    ask, undo, removeChip, switchChip, feedback, surprise, explore, filter, cancel, toggleSpeech, listen,
    toggleHandsFree, newVisitor,
  } = useConversation()
  const status = useSession((s) => s.status)
  const playing = useSession((s) => s.playing)
  const listening = useSession((s) => s.listening)
  const handsFree = useSession((s) => s.handsFree)
  const speakWanted = useSession((s) => s.speakWanted)
  const speakOn = useSession((s) => s.speakOn)
  const exchanges = useSession((s) => s.exchanges)
  const shelf = useSession((s) => s.shelf)
  const shelfReply = useSession((s) => s.shelfReply)
  const error = useSession((s) => s.error)
  const latest = [...exchanges].reverse().find((e) => e.response)?.response

  // A question asked on the landing page arrives as ?q=; ask it once, then drop it from the
  // address so a reload doesn't ask again.
  useEffect(() => {
    const question = new URLSearchParams(window.location.search).get('q')?.trim()
    if (!question) return
    window.history.replaceState(null, '', window.location.pathname)
    ask(question)
  }, [ask])

  return (
    <div className="flex h-full flex-col">
      <a
        href="#results"
        className="sr-only rounded-md bg-accent px-3 py-2 text-card focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-10"
      >
        Skip to results
      </a>
      <Announcer />
      <header className="flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-line px-4 py-3 md:px-6">
        <h1 className="font-serif text-xl font-semibold tracking-tight">Shelfwise</h1>
        <div className="order-last w-full md:order-none md:max-w-2xl md:flex-1">
          <SearchBar onAsk={ask} onCancel={cancel} listening={listening} onListen={listen} />
          <div className="mt-2 px-1">
            <ModeBar onSurprise={surprise} onExplore={explore} onFilters={filter} />
          </div>
        </div>
        <div className="ml-auto flex items-center gap-4">
          <HandsFreeToggle on={handsFree} onToggle={toggleHandsFree} />
          <SpeakToggle wanted={speakWanted} on={speakOn} onToggle={toggleSpeech} />
        </div>
        <button
          type="button"
          onClick={() => void newVisitor()}
          className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-ink"
        >
          <UserPlus className="size-4" aria-hidden="true" /> New visitor
        </button>
      </header>

      <div className="flex min-h-0 flex-1 flex-col-reverse md:flex-row">
        <aside className="flex max-h-[40vh] w-full flex-col gap-4 overflow-y-auto border-t border-line p-4 md:max-h-none md:w-80 md:shrink-0 md:border-t-0 md:border-r">
          <AvatarSlot status={playing ? 'speaking' : status} />
          <ConversationPanel exchanges={exchanges} />
        </aside>

        <main
          id="results"
          tabIndex={-1}
          className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4 focus:outline-none md:p-6"
        >
          <div className="flex flex-wrap items-center gap-3">
            <ChipBar chips={latest?.chips ?? []} onRemove={removeChip} onSwitch={switchChip} />
            {latest?.can_undo && (
              <button
                type="button"
                onClick={undo}
                className="inline-flex items-center gap-1 text-sm text-accent hover:underline"
              >
                <RotateCcw className="size-3.5" aria-hidden="true" /> Back to previous search
              </button>
            )}
          </div>
          {error && (
            <p role="alert" className="rounded-md bg-out-soft px-3 py-2 text-sm text-out">
              {error}
            </p>
          )}
          <ResultsShelf
            shelf={shelf}
            reply={shelfReply}
            writing={status === 'writing'}
            onAsk={ask}
            onFeedback={feedback}
          />
        </main>
      </div>
      <PipelineInspector response={latest} />
    </div>
  )
}
