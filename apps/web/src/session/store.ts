// What the screen shows, built from the server's events. Kept free of network code so the
// rules ("cards replace the shelf, chat doesn't") are testable on their own.
import { create } from 'zustand'

import type { Reply, ServerEvent, TurnResponse } from '../api/types'

export type Status = 'starting' | 'ready' | 'listening' | 'searching' | 'writing' | 'speaking' | 'offline'

export interface Exchange {
  key: number // local, for React lists
  said: string
  turn?: number
  response?: TurnResponse
  reply?: Reply
  cancelled?: boolean
  pending: boolean
  fixed?: { heard: string; catalog: string }[] // names respelled in a spoken question
}

// Routes whose books belong on the shelf. "chat" and "clarify" leave the shelf as it was.
const SHELF_ROUTES = new Set(['search', 'surprise', 'explain', 'compare', 'start_over'])

export interface SessionState {
  sessionId: string | null
  status: Status
  exchanges: Exchange[]
  shelf: TurnResponse | null // the turn whose books are on screen
  shelfReply: Reply | null
  error: string | null
  speakWanted: boolean // the reader's "read aloud" setting
  speakOn: boolean | null // what the server confirmed: false when it has no speech model
  playing: boolean // speech is coming out of the speakers now
  listening: boolean // the microphone is open
  setSpeakWanted: (on: boolean) => void
  setPlaying: (playing: boolean) => void
  setSession: (sessionId: string | null) => void
  setOnline: (online: boolean) => void
  said: (text: string) => void
  receive: (event: ServerEvent) => void
  clear: () => void
}

let nextKey = 1

const SPEAK_KEY = 'shelfwise.speak'

const LISTENING_PROBLEMS: Record<string, string> = {
  'no speech': 'I didn’t hear anything. Tap the microphone and try again.',
  unavailable: 'Voice input isn’t set up on the server (make download-stt).',
}

// A per-browser convenience: private windows and blocked storage just start with speech off.
function readSpeakSetting(): boolean {
  try {
    return globalThis.localStorage?.getItem(SPEAK_KEY) === 'on'
  } catch {
    return false
  }
}

function writeSpeakSetting(on: boolean): void {
  try {
    globalThis.localStorage?.setItem(SPEAK_KEY, on ? 'on' : 'off')
  } catch {
    // not remembered; the setting still holds for this page
  }
}

function update(exchanges: Exchange[], turn: number, change: Partial<Exchange>): Exchange[] {
  return exchanges.map((e) => (e.turn === turn ? { ...e, ...change } : e))
}

export const useSession = create<SessionState>((set) => ({
  sessionId: null,
  status: 'starting',
  exchanges: [],
  shelf: null,
  shelfReply: null,
  error: null,
  speakWanted: readSpeakSetting(),
  speakOn: null,
  playing: false,
  listening: false,

  setSpeakWanted: (on) => {
    writeSpeakSetting(on)
    set({ speakWanted: on, speakOn: on ? null : false })
  },
  setPlaying: (playing) => set({ playing }),
  setSession: (sessionId) => set({ sessionId }),
  setOnline: (online) =>
    set((s) => ({ status: online ? (s.status === 'offline' ? 'ready' : s.status) : 'offline' })),

  said: (text) =>
    set((s) => ({
      status: 'searching',
      error: null,
      exchanges: [...s.exchanges, { key: nextKey++, said: text, pending: true }],
    })),

  receive: (event) =>
    set((s) => {
      switch (event.type) {
        case 'turn': {
          const { type: _type, ...response } = event
          const exchanges = [...s.exchanges]
          const waiting = exchanges.findLastIndex((e) => e.pending && e.turn === undefined)
          const entry = { turn: response.turn, response }
          if (waiting >= 0) exchanges[waiting] = { ...exchanges[waiting], ...entry }
          else exchanges.push({ key: nextKey++, said: '', pending: true, ...entry })
          const onShelf = SHELF_ROUTES.has(response.route)
          return {
            exchanges,
            status: 'writing',
            shelf: onShelf ? (response.route === 'start_over' ? null : response) : s.shelf,
            shelfReply: onShelf ? null : s.shelfReply,
          }
        }
        case 'reply_piece': {
          // The reply so far: the notes show on the cards as the model finishes each one.
          const exchange = s.exchanges.find((e) => e.turn === event.turn)
          if (!exchange) return {}
          const sofar: Reply = exchange.reply ?? { intro: '', items: [], follow_up: '', source: 'llm', problems: [], attempts: 0, ms: 0 }
          const next: Reply = { ...sofar }
          if (event.kind === 'intro') next.intro = event.text
          if (event.kind === 'follow_up') next.follow_up = event.text
          if (event.kind === 'item' && event.work_id != null) {
            next.items = [...sofar.items.filter((i) => i.work_id !== event.work_id),
              { work_id: event.work_id, why: event.text, source: event.source }]
          }
          return {
            exchanges: update(s.exchanges, event.turn, { reply: next }),
            shelfReply: s.shelf?.turn === event.turn ? next : s.shelfReply,
          }
        }
        case 'reply': {
          const isShelf = s.shelf?.turn === event.turn
          return {
            exchanges: update(s.exchanges, event.turn, { reply: event.reply }),
            shelfReply: isShelf ? event.reply : s.shelfReply,
          }
        }
        case 'audio':
        case 'speech_start':
          return {} // handled by the speech player and the microphone, not drawn
        case 'listening': {
          if (event.on) return { listening: true, status: 'listening', error: null }
          const message = LISTENING_PROBLEMS[event.reason ?? '']
          const waiting = event.reason === 'heard' // a transcript follows
          return { listening: false, status: waiting ? 'searching' : 'ready', ...(message && { error: message }) }
        }
        case 'transcript':
          if (!event.text) return { error: 'I couldn’t make that out. Try again, or type it.', status: 'ready' }
          return {
            status: 'searching',
            exchanges: [...s.exchanges, { key: nextKey++, said: event.text, pending: true, fixed: event.fixed }],
          }
        case 'speak':
          return { speakOn: event.on }
        case 'done':
          return { exchanges: update(s.exchanges, event.turn, { pending: false }), status: 'ready' }
        case 'cancelled':
          return { exchanges: update(s.exchanges, event.turn, { pending: false, cancelled: true }) }
        case 'error':
          return {
            error: event.message,
            status: 'ready',
            exchanges: s.exchanges.map((e) => (e.pending ? { ...e, pending: false } : e)),
          }
      }
    }),

  clear: () => set({ exchanges: [], shelf: null, shelfReply: null, error: null }),
}))
