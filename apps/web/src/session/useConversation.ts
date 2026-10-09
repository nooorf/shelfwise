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
  toggleSpeech: () => void
  listen: () => void
  newVisitor: () => Promise<void>
}

// One audio output and one microphone per page.
export const speech = new SpeechPlayer((playing) => useSession.getState().setPlaying(playing))
const microphone = new Microphone()

function onEvent(event: ServerEvent): void {
  if (event.type === 'turn') speech.seen(event.turn)
  if (event.type === 'speech_start') speech.stop() // barge-in by voice
  if (event.type === 'listening' && !event.on) microphone.stop() // the server heard the end
  if (event.type === 'audio') void speech.play(event.turn, event.wav)
  useSession.getState().receive(event)
}

/** `outbox`: messages sent before any socket existed (a quick first question while the page
 * is still starting a session); they go to the new socket, which sends them once it's open. */
async function openSession(
  socket: MutableRefObject<SessionSocket | null>,
  outbox: ClientMessage[],
): Promise<void> {
  const { setSession, setOnline, clear } = useSession.getState()
  socket.current?.close()
  try {
    const id = await startSession()
    setSession(id)
    const next = new SessionSocket(socketUrl(id), {
      onEvent,
      onOpenChange: (open) => {
        setOnline(open)
        // Each new socket starts with speech off on the server: say what the reader wants.
        if (open) next.send({ type: 'speak', on: useSession.getState().speakWanted })
      },
      onSessionGone: () => {
        clear()
        void openSession(socket, outbox)
      },
    })
    socket.current = next
    for (const message of outbox.splice(0)) next.send(message)
    next.connect()
  } catch {
    setOnline(false)
    setTimeout(() => void openSession(socket, outbox), 3000) // the API isn't up yet
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

export function useConversation(): Conversation {
  const socket = useRef<SessionSocket | null>(null)
  const outbox = useRef<ClientMessage[]>([])
  const sessionId = useSession((s) => s.sessionId)

  useEffect(() => {
    void openSession(socket, outbox.current)
    // The latest socket, reconnects included, is the one to close: reading it late is the point.
    // oxlint-disable-next-line react-hooks/exhaustive-deps
    return () => socket.current?.close()
  }, [])

  const send = useCallback((message: ClientMessage) => {
    speech.stop()
    if (useSession.getState().speakWanted) speech.unlock()
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

  const toggleSpeech = useCallback(() => {
    const on = !useSession.getState().speakWanted
    useSession.getState().setSpeakWanted(on)
    send({ type: 'speak', on })
  }, [send])

  const listen = useCallback(() => {
    if (microphone.open) {
      microphone.stop()
      send({ type: 'listen', on: false }) // "done talking": transcribe what was heard
      return
    }
    send({ type: 'listen', on: true })
    microphone.start((pcm) => socket.current?.sendAudio(pcm)).catch(() => {
      microphone.stop()
      send({ type: 'listen', on: false })
      useSession.setState({ error: 'The microphone isn’t available: check the browser’s permission.' })
    })
  }, [send])

  const newVisitor = useCallback(async () => {
    speech.stop()
    microphone.stop()
    socket.current?.close()
    socket.current = null // until the new session's socket exists, sends wait in the outbox
    outbox.current.splice(0) // nothing from the previous visitor carries over
    if (sessionId) await endSession(sessionId)
    useSession.getState().clear()
    await openSession(socket, outbox.current)
  }, [sessionId])

  return {
    ask, undo, removeChip, switchChip, feedback, surprise, explore, filter, cancel, toggleSpeech,
    listen, newVisitor,
  }
}
