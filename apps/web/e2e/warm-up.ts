// Before the tests: the first search after the API starts loads the embedding model (tens of
// seconds on the Mac); pay that once here, not inside the first test's timeout. Then record
// the spoken question the voice test plays into Chromium's fake microphone: the API's own
// voice (Kokoro), with silence around it so the VAD hears a start and an end.
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const API = 'http://localhost:8000/api/v1'
export const QUESTION = 'Gothic horror novels, please.'
export const QUESTION_WAV = fileURLToPath(new URL('./.cache/question.wav', import.meta.url))

async function post(path: string, body: unknown): Promise<Response> {
  return fetch(`${API}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(180_000),
  })
}

/** A 16-bit mono WAV with `before` and `after` seconds of silence around `wav`'s samples. */
function padded(wav: Buffer, before: number, after: number): Buffer {
  const rate = wav.readUInt32LE(24)
  const samples = wav.subarray(44)
  const data = Buffer.concat([Buffer.alloc(rate * 2 * before), samples, Buffer.alloc(rate * 2 * after)])
  const header = Buffer.alloc(44)
  header.write('RIFF', 0)
  header.writeUInt32LE(36 + data.length, 4)
  header.write('WAVEfmt ', 8)
  header.writeUInt32LE(16, 16)
  header.writeUInt16LE(1, 20) // PCM
  header.writeUInt16LE(1, 22) // mono
  header.writeUInt32LE(rate, 24)
  header.writeUInt32LE(rate * 2, 28)
  header.writeUInt16LE(2, 32)
  header.writeUInt16LE(16, 34)
  header.write('data', 36)
  header.writeUInt32LE(data.length, 40)
  return Buffer.concat([header, data])
}

export default async function warmUp(): Promise<void> {
  const search = await post('/search', { query: 'warm up', limit: 1 })
  if (!search.ok) throw new Error(`the API did not answer a search (${search.status})`)
  const speech = await post('/speech', { text: QUESTION })
  if (!speech.ok) return // no TTS model: the voice test skips itself
  mkdirSync(dirname(QUESTION_WAV), { recursive: true })
  writeFileSync(QUESTION_WAV, padded(Buffer.from(await speech.arrayBuffer()), 1, 3))
}
