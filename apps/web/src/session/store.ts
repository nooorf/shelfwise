// What the screen shows, built from the server's events. Kept free of network code so the
// rules ("cards replace the shelf, chat doesn't") are testable on their own.
import { create } from 'zustand'

import type { Reply, ServerEvent, TurnResponse } from '../api/types'

export type Status = 'starting' | 'ready' | 'searching' | 'writing' | 'offline'

export interface Exchange {
  key: number // local, for React lists
  said: string
  turn?: number
  response?: TurnResponse
  reply?: Reply
  cancelled?: boolean
  pending: boolean
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
  setSession: (sessionId: string | null) => void
  setOnline: (online: boolean) => void
  said: (text: string) => void
  receive: (event: ServerEvent) => void
  clear: () => void
}

let nextKey = 1

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
        case 'reply': {
          const isShelf = s.shelf?.turn === event.turn
          return {
            exchanges: update(s.exchanges, event.turn, { reply: event.reply }),
            shelfReply: isShelf ? event.reply : s.shelfReply,
          }
        }
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
