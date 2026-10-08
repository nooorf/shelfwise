// Starts a session, keeps its socket open, and exposes what the UI can do. An expired
// session (kiosk timeout) quietly becomes a new, empty one.
import { useCallback, useEffect, useRef } from 'react'
import type { MutableRefObject } from 'react'

import { endSession, socketUrl, startSession } from '../api/client'
import type { Chip } from '../api/types'
import { SessionSocket } from './socket'
import { useSession } from './store'

export interface Conversation {
  ask: (text: string) => void
  undo: () => void
  removeChip: (chip: Chip) => void
  cancel: () => void
  newVisitor: () => Promise<void>
}

async function openSession(socket: MutableRefObject<SessionSocket | null>): Promise<void> {
  const { setSession, setOnline, receive, clear } = useSession.getState()
  socket.current?.close()
  try {
    const id = await startSession()
    setSession(id)
    const next = new SessionSocket(socketUrl(id), {
      onEvent: receive,
      onOpenChange: setOnline,
      onSessionGone: () => {
        clear()
        void openSession(socket)
      },
    })
    socket.current = next
    next.connect()
  } catch {
    setOnline(false)
    setTimeout(() => void openSession(socket), 3000) // the API isn't up yet
  }
}

export function useConversation(): Conversation {
  const socket = useRef<SessionSocket | null>(null)
  const sessionId = useSession((s) => s.sessionId)

  useEffect(() => {
    void openSession(socket)
    // The latest socket, reconnects included, is the one to close: reading it late is the point.
    // oxlint-disable-next-line react-hooks/exhaustive-deps
    return () => socket.current?.close()
  }, [])

  const ask = useCallback((text: string) => {
    const trimmed = text.trim()
    if (!trimmed) return
    useSession.getState().said(trimmed)
    socket.current?.send({ type: 'text', text: trimmed })
  }, [])

  const undo = useCallback(() => {
    useSession.getState().said('Undo')
    socket.current?.send({ type: 'undo' })
  }, [])

  const removeChip = useCallback((chip: Chip) => {
    useSession.getState().said(`Remove "${chip.label}"`)
    socket.current?.send({ type: 'remove_chip', field: chip.field, label: chip.label })
  }, [])

  const cancel = useCallback(() => socket.current?.send({ type: 'cancel' }), [])

  const newVisitor = useCallback(async () => {
    socket.current?.close()
    if (sessionId) await endSession(sessionId)
    useSession.getState().clear()
    await openSession(socket)
  }, [sessionId])

  return { ask, undo, removeChip, cancel, newVisitor }
}
