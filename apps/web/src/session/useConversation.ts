// Starts a session, keeps its socket open, and exposes what the UI can do. An expired
// session (kiosk timeout) quietly becomes a new, empty one. Any action stops speech first
// (barge-in), and, being a user gesture, lets the page make sound.
import { useCallback, useEffect, useRef } from 'react'
import type { MutableRefObject } from 'react'

import { endSession, socketUrl, startSession } from '../api/client'
import type { BookResult, Chip, ClientMessage, Filters, ServerEvent } from '../api/types'
import { Microphone } from './microphone'
import { SpeechPlayer } from './player'
import { SessionSocket } from './socket'
import { useSession } from './store'

export interface Conversation {
  ask: (text: string) => void
  undo: () => void
  removeChip: (chip: Chip) => void
  switchChip: (chip: Chip) => void
  feedback: (book: BookResult, more: boolean) => void
  surprise: () => void
  explore: (genre: string) => void
  filter: (filters: Filters) => void
  cancel: () => void
  listen: () => void
  toggleHandsFree: () => void
  newVisitor: () => Promise<void>
}

// One audio output and one microphone per page.
export const speech = new SpeechPlayer((playing) => useSession.getState().setPlaying(playing))
const microphone = new Microphone()
let liveSocket: SessionSocket | null = null // the session's current socket, for the mic
let speaking = false // whether the page wants spoken answers: the live session yes, the chat no

// While the assistant talks, only frames this loud reach the server: someone speaking to the
// kiosk gets through (barge-in); its own voice leaking past echo cancellation doesn't.
export const BARGE_IN_RMS = 0.03

export function frameLevel(pcm: ArrayBuffer): number {
  const samples = new Int16Array(pcm)
  let sum = 0
  for (const s of samples) sum += (s / 32768) ** 2
  return Math.sqrt(sum / Math.max(samples.length, 1))
}

let level = 0 // the microphone's loudness, frame by frame, for the live page's mic ring

/** How loud the microphone is now (RMS, 0-1); 0 when it's closed. */
export function micLevel(): number {
  return microphone.open ? level : 0
}

function forward(pcm: ArrayBuffer): void {
  level = frameLevel(pcm)
  if (speech.playing && level < BARGE_IN_RMS) return
  liveSocket?.sendAudio(pcm)
}

/** Hands-free: ask the server to listen again, without the barge-in a user action makes. */
function keepListening(): void {
  if (useSession.getState().handsFree && microphone.open) liveSocket?.send({ type: 'listen', on: true })
}

function onEvent(event: ServerEvent): void {
  const handsFree = useSession.getState().handsFree
  if (event.type === 'turn') {
    speech.seen(event.turn)
    keepListening() // the answer is on screen: listen for the next question (or a barge-in)
  }
  if (event.type === 'speech_start') speech.stop() // barge-in by voice
  if (event.type === 'transcript' && !event.text) keepListening() // unintelligible: try again
  if (event.type === 'listening' && !event.on) {
    if (!handsFree || event.reason === 'unavailable') {
      microphone.stop() // the server heard the end
      if (handsFree) useSession.getState().setHandsFree(false)
    } else if (event.reason === 'no speech') {
      keepListening() // nobody spoke: just keep listening, no error
    }
  }
  if (event.type === 'audio') void speech.play(event.turn, event.wav)
  useSession.getState().receive(event)
}

/** `outbox`: messages sent before any socket existed (a quick first question while the page
 * is still starting a session); they go to the new socket, which sends them once it's open.
 * `current`: false once the page has moved on (unmounted, or a new visitor) while this session
 * was starting. Its late answer is then dropped and the session ended, so it can't replace a
 * newer socket: in development React mounts twice, and the first session used to win the race
 * now and then, sending a message to one session and the next to another. */
async function openSession(
  socket: MutableRefObject<SessionSocket | null>,
  outbox: ClientMessage[],
  current: () => boolean,
): Promise<void> {
  const { setSession, setOnline, clear } = useSession.getState()
  socket.current?.close()
  try {
    const id = await startSession()
    if (!current()) {
      void endSession(id)
      return
    }
    setSession(id)
    const next = new SessionSocket(socketUrl(id), {
      onEvent,
      onOpenChange: (open) => {
        setOnline(open)
        // Each new socket starts with speech off on the server: say what the page wants.
        if (open) next.send({ type: 'speak', on: speaking })
        if (open) keepListening() // a reconnect mid hands-free: the server forgot it was listening
      },
      onSessionGone: () => {
        if (!current()) return
        clear()
        void openSession(socket, outbox, current)
      },
    })
    socket.current = next
    liveSocket = next
    for (const message of outbox.splice(0)) next.send(message)
    next.connect()
  } catch {
    setOnline(false)
    if (current()) setTimeout(() => current() && void openSession(socket, outbox, current), 3000) // the API isn't up yet
  }
}

/** "at most 300 pages, 2010–2020, available now", for the conversation column. */
export function filtersInWords(f: Filters): string {
  const words: string[] = []
  if (f.pages_max != null) words.push(`at most ${f.pages_max} pages`)
  if (f.year_from != null && f.year_to != null) words.push(`${f.year_from}–${f.year_to}`)
  else if (f.year_from != null) words.push(`${f.year_from} or later`)
  else if (f.year_to != null) words.push(`${f.year_to} or earlier`)
  if (f.available_now === true) words.push('available now')
  if (f.available_now === false) words.push('not only available now')
  return words.join(', ')
}

/** `speech`: whether the server speaks its answers (the live session) or not (the text chat). */
export function useConversation({ speech: withSpeech }: { speech: boolean }): Conversation {
  const socket = useRef<SessionSocket | null>(null)
  const outbox = useRef<ClientMessage[]>([])
  const sessionId = useSession((s) => s.sessionId)
  const generation = useRef(0) // which session start is the page's current one
  speaking = withSpeech

  useEffect(() => {
    // A page opens a new session, so it starts with an empty conversation too.
    useSession.getState().clear()
    const mine = ++generation.current
    void openSession(socket, outbox.current, () => generation.current === mine)
    return () => {
      generation.current += 1
      // The latest socket, reconnects included, is the one to close: reading it late is the point.
      // oxlint-disable-next-line react-hooks/exhaustive-deps
      socket.current?.close()
    }
  }, [])

  const send = useCallback((message: ClientMessage) => {
    speech.stop()
    if (speaking) speech.unlock()
    if (socket.current) socket.current.send(message)
    else outbox.current.push(message)
  }, [])

  const ask = useCallback((text: string) => {
    const trimmed = text.trim()
    if (!trimmed) return
    useSession.getState().said(trimmed)
    send({ type: 'text', text: trimmed })
  }, [send])

  const undo = useCallback(() => {
    useSession.getState().said('Undo')
    send({ type: 'undo' })
  }, [send])

  const removeChip = useCallback((chip: Chip) => {
    useSession.getState().said(`Remove "${chip.label}"`)
    send({ type: 'remove_chip', field: chip.field, label: chip.label })
  }, [send])

  const switchChip = useCallback((chip: Chip) => {
    const strength = chip.strength === 'hard' ? 'soft' : 'hard'
    useSession.getState().said(`“${chip.label}”: ${strength === 'hard' ? 'must' : 'preferred'}`)
    send({ type: 'chip_strength', field: chip.field, label: chip.label, strength })
  }, [send])

  const feedback = useCallback((book: BookResult, more: boolean) => {
    useSession.getState().said(`${more ? 'More' : 'Less'} like “${book.title}”`)
    send({ type: more ? 'more_like' : 'less_like', work_id: book.work_id })
  }, [send])

  const surprise = useCallback(() => {
    useSession.getState().said('Surprise me')
    send({ type: 'surprise' })
  }, [send])

  const explore = useCallback((genre: string) => {
    useSession.getState().said(`Explore ${genre}`)
    send({ type: 'explore', genre })
  }, [send])

  const filter = useCallback((filters: Filters) => {
    useSession.getState().said(`Filters: ${filtersInWords(filters)}`)
    send({ type: 'filters', ...filters })
  }, [send])

  const cancel = useCallback(() => send({ type: 'cancel' }), [send])

  const listen = useCallback(() => {
    if (microphone.open) {
      useSession.getState().setHandsFree(false) // the mic button ends hands-free too
      microphone.stop()
      send({ type: 'listen', on: false }) // "done talking": transcribe what was heard
      return
    }
    send({ type: 'listen', on: true })
    microphone.start(forward).catch(() => {
      useSession.getState().setHandsFree(false)
      microphone.stop()
      send({ type: 'listen', on: false })
      useSession.setState({ error: 'The microphone isn’t available: check the browser’s permission.' })
    })
  }, [send])

  const toggleHandsFree = useCallback(() => {
    const on = !useSession.getState().handsFree
    useSession.getState().setHandsFree(on)
    if (on && !microphone.open) listen()
    if (!on && microphone.open) {
      microphone.stop()
      send({ type: 'listen', on: false })
    }
  }, [listen, send])

  const newVisitor = useCallback(async () => {
    speech.stop()
    microphone.stop()
    socket.current?.close()
    socket.current = null // until the new session's socket exists, sends wait in the outbox
    outbox.current.splice(0) // nothing from the previous visitor carries over
    if (sessionId) await endSession(sessionId)
    useSession.getState().clear()
    const mine = ++generation.current
    await openSession(socket, outbox.current, () => generation.current === mine)
  }, [sessionId])

  return {
    ask, undo, removeChip, switchChip, feedback, surprise, explore, filter, cancel,
    listen, toggleHandsFree, newVisitor,
  }
}
