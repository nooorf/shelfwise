// REST calls: sessions are created and ended over HTTP; turns go over the WebSocket.

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
