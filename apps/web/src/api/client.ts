// REST calls: sessions are created and ended over HTTP; turns go over the WebSocket.
import type { Bench, BookDetail, GenreCount } from './types'

export async function startSession(): Promise<string> {
  const response = await fetch('/api/v1/sessions', { method: 'POST' })
  if (!response.ok) throw new Error(`could not start a session (${response.status})`)
  const body = (await response.json()) as { session_id: string }
  return body.session_id
}

/** "New visitor": the server forgets the conversation now, not at expiry. */
export async function endSession(sessionId: string): Promise<void> {
  await fetch(`/api/v1/sessions/${sessionId}`, { method: 'DELETE' })
}

export function socketUrl(sessionId: string, location: Location = window.location): string {
  const scheme = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${scheme}://${location.host}/api/v1/sessions/${sessionId}/stream`
}

/** One book for the drawer: the card's facts, the description, tags, editions and copies. */
export async function getBook(workId: number): Promise<BookDetail> {
  const response = await fetch(`/api/v1/books/${workId}`)
  if (!response.ok) throw new Error(`could not load the book (${response.status})`)
  return (await response.json()) as BookDetail
}

/** Explore: every genre in the catalog with its number of books, largest first. */
export async function getGenres(): Promise<GenreCount[]> {
  const response = await fetch('/api/v1/genres')
  if (!response.ok) throw new Error(`could not load the genres (${response.status})`)
  return (await response.json()) as GenreCount[]
}

/** The benchmark dashboard: the newest dev-split retrieval and parser reports. */
export async function getBench(): Promise<Bench> {
  const response = await fetch('/api/v1/bench')
  if (!response.ok) throw new Error(`could not load the benchmarks (${response.status})`)
  return (await response.json()) as Bench
}
