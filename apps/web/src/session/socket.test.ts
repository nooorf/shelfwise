import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { SESSION_GONE, SessionSocket } from './socket'

class FakeSocket {
  static OPEN = 1
  readyState = 0
  sent: string[] = []
  onopen: (() => void) | null = null
  onmessage: ((m: { data: string }) => void) | null = null
  onclose: ((e: { code: number }) => void) | null = null
  send(data: string) { this.sent.push(data) }
  close() {}
  open() { this.readyState = 1; this.onopen?.() }
}

describe('session socket', () => {
  let sockets: FakeSocket[]
  const handlers = { onEvent: vi.fn(), onOpenChange: vi.fn(), onSessionGone: vi.fn() }

  beforeEach(() => {
    vi.useFakeTimers()
    vi.stubGlobal('WebSocket', { OPEN: 1 })
    sockets = []
    Object.values(handlers).forEach((h) => h.mockReset())
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  function connect() {
    const socket = new SessionSocket('ws://x', handlers, () => {
      const s = new FakeSocket()
      sockets.push(s)
      return s as unknown as WebSocket
    })
    socket.connect()
    return socket
  }

  it('queues messages until the socket opens', () => {
    const socket = connect()
    socket.send({ type: 'text', text: 'hi' })
    expect(sockets[0].sent).toEqual([])
    sockets[0].open()
    expect(sockets[0].sent).toEqual([JSON.stringify({ type: 'text', text: 'hi' })])
  })

  it('reconnects with backoff, but not when the session is gone', () => {
    connect()
    sockets[0].open()
    sockets[0].onclose?.({ code: 1006 })
    vi.advanceTimersByTime(499)
    expect(sockets).toHaveLength(1)
    vi.advanceTimersByTime(1)
    expect(sockets).toHaveLength(2)

    sockets[1].onclose?.({ code: SESSION_GONE })
    vi.advanceTimersByTime(10_000)
    expect(sockets).toHaveLength(2)
    expect(handlers.onSessionGone).toHaveBeenCalledOnce()
  })
})
