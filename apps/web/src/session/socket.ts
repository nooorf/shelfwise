// The session WebSocket, kept open across turns. Reconnects with exponential backoff; a
// close code of 4404 means the session expired on the server, so the caller starts a new one.
import type { ClientMessage, ServerEvent } from '../api/types'

const BACKOFF_MS = [500, 1000, 2000, 4000, 8000]
export const SESSION_GONE = 4404

export interface SocketHandlers {
  onEvent: (event: ServerEvent) => void
  onOpenChange: (open: boolean) => void
  onSessionGone: () => void
}

export class SessionSocket {
  private ws: WebSocket | null = null
  private attempts = 0
  private closed = false
  private queue: ClientMessage[] = []
  private retry: ReturnType<typeof setTimeout> | null = null
  private readonly url: string
  private readonly handlers: SocketHandlers
  private readonly makeSocket: (url: string) => WebSocket

  constructor(
    url: string,
    handlers: SocketHandlers,
    makeSocket: (url: string) => WebSocket = (u) => new WebSocket(u),
  ) {
    this.url = url
    this.handlers = handlers
    this.makeSocket = makeSocket
  }

  connect(): void {
    this.closed = false
    const ws = this.makeSocket(this.url)
    this.ws = ws
    ws.onopen = () => {
      this.attempts = 0
      this.handlers.onOpenChange(true)
      for (const message of this.queue.splice(0)) ws.send(JSON.stringify(message))
    }
    ws.onmessage = (message) => {
      this.handlers.onEvent(JSON.parse(String(message.data)) as ServerEvent)
    }
    ws.onclose = (event) => {
      this.handlers.onOpenChange(false)
      if (this.closed) return
      if (event.code === SESSION_GONE) {
        this.handlers.onSessionGone()
        return
      }
      const delay = BACKOFF_MS[Math.min(this.attempts, BACKOFF_MS.length - 1)]
      this.attempts += 1
      this.retry = setTimeout(() => this.connect(), delay)
    }
  }

  /** Sends now, or as soon as the socket is open. */
  send(message: ClientMessage): void {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(message))
    else this.queue.push(message)
  }

  /** Microphone audio: sent if the socket is open, dropped otherwise (it's live, not queued). */
  sendAudio(pcm: ArrayBuffer): void {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(pcm)
  }

  close(): void {
    this.closed = true
    if (this.retry) clearTimeout(this.retry)
    this.ws?.close()
  }
}
