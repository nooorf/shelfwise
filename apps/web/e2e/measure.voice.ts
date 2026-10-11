// The voice measurements (`make measure`; design doc §21, §32): spoken questions into the live
// page's microphone, answers out of its speakers, timed on the page's own clock by the probe
// (src/session/probe.ts). Each question is the API's own voice (Kokoro) played into a fake
// microphone that stands in for getUserMedia, so the page, the socket, the VAD, Whisper, the
// parser, search and speech all run as they do for a visitor. The same questions run twice,
// avatar off and on (time to first audio must not change), then the page is loaded a few
// times from a cold cache for the avatar's load time. A headed browser: headless Chromium
// draws WebGL in software, too slow for the avatar. Writes eval/reports/<time>_<git>_voice.json,
// which /bench shows. UTTERANCES (default 30) and LOADS (default 5) change the counts.
import { execSync } from 'node:child_process'
import { mkdirSync, writeFileSync } from 'node:fs'
import { cpus, totalmem } from 'node:os'
import { fileURLToPath } from 'node:url'

import { expect, test } from '@playwright/test'
import type { Browser, Page } from '@playwright/test'

import type { Log, Utterance } from './voice-stats.ts'
import { pairedTtfa, spread, summarise, utterance } from './voice-stats.ts'

const API = 'http://localhost:8000/api/v1'
const UTTERANCES = Number(process.env.UTTERANCES ?? 30)
const LOADS = Number(process.env.LOADS ?? 5)
const REPORTS = fileURLToPath(new URL('../../../eval/reports/', import.meta.url))

// Requests of the kinds people make at the desk: genre, mood, author, title, learning,
// similarity, with and without constraints. Short, as said aloud.
const QUESTIONS = [
  'Gothic horror novels, please.',
  'Something like The Hunger Games.',
  'A cozy mystery for the weekend.',
  'Books by Agatha Christie.',
  'I want to learn Python from scratch.',
  'A short science fiction novel.',
  'Do you have Pride and Prejudice?',
  'Fantasy with dragons, but nothing too dark.',
  'A funny book for a long flight.',
  'Historical fiction set in Japan.',
  'Something by Neil Gaiman for kids.',
  'A thriller that is available now.',
  'Books about the history of science.',
  'A romance that is not too long.',
  'Poetry for someone new to poetry.',
  'Something like Gone Girl.',
  'A classic Russian novel.',
  'Self help books about habits.',
  'A graphic novel for teenagers.',
  'Space opera from the last ten years.',
  'Books about World War Two.',
  'A sad book that will make me cry.',
  'Detective stories set in London.',
  'An introduction to economics.',
  'Something by Stephen King, but not horror.',
  'A book about climate change.',
  'Magical realism, please.',
  'An easy book about the stock market.',
  'Dystopian novels without romance.',
  'A biography of a scientist.',
]

// Stands in for the microphone: getUserMedia gets a stream that plays what window.__say is
// given, and silence otherwise. A fresh stream each time: the page stops its tracks after a turn.
const fakeMicrophone = (avatar: 'on' | 'off') => `
  localStorage.setItem('shelfwise.avatar', '${avatar}')
  let context = null
  let into = null
  const audio = () => (context ??= new AudioContext())
  navigator.mediaDevices.getUserMedia = async () => {
    await audio().resume()
    into = audio().createMediaStreamDestination()
    return into.stream
  }
  // Plays a base64 WAV into the microphone; resolves after it ends with when (page clock, ms)
  // its last sound went in: the last 10 ms window louder than the lip-sync's silence (0.015).
  window.__say = async (wav) => {
    const c = audio()
    await c.resume()
    const buffer = await c.decodeAudioData(Uint8Array.from(atob(wav), (ch) => ch.charCodeAt(0)).buffer)
    const samples = buffer.getChannelData(0)
    const step = Math.round(buffer.sampleRate * 0.01)
    let last = 0
    for (let i = 0; i + step <= samples.length; i += step) {
      let sum = 0
      for (let j = i; j < i + step; j++) sum += samples[j] * samples[j]
      if (Math.sqrt(sum / step) > 0.015) last = (i + step) / buffer.sampleRate
    }
    const source = c.createBufferSource()
    source.buffer = buffer
    source.connect(into)
    const at = c.currentTime + 0.05
    const until = performance.now() + (at - c.currentTime + last) * 1000
    source.start(at)
    await new Promise((done) => (source.onended = done))
    return until
  }
`

/** Every clip heard and the turn done, half a second ago. */
const SETTLED = `(() => {
  const log = window.__probe.peek()
  if (!log.events.some((e) => e.type === 'done' || e.type === 'error')) return false
  const end = Math.max(0, ...log.clips.map((c) => c.heard + c.duration))
  return performance.now() > end + 500
})()`

async function speech(text: string): Promise<string> {
  const response = await fetch(`${API}/speech`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  })
  if (!response.ok) throw new Error(`no voice for the questions (${response.status}): run make download-tts`)
  return Buffer.from(await response.arrayBuffer()).toString('base64')
}

/** Asks one question out loud; null if no answer was heard within the time limit. */
async function ask(page: Page, wav: string): Promise<Utterance | null> {
  await page.evaluate('window.__probe.take()')
  await page.getByRole('button', { name: 'Speak' }).click()
  await expect(page.getByRole('button', { name: 'Stop listening' })).toBeVisible()
  await page.waitForTimeout(500) // the microphone's worklet starting
  const spokeUntil = (await page.evaluate(`window.__say(${JSON.stringify(wav)})`)) as number
  try {
    await page.waitForFunction(SETTLED, undefined, { timeout: 90_000, polling: 250 })
  } catch {
    return null
  }
  return utterance((await page.evaluate('window.__probe.take()')) as Log, spokeUntil)
}

async function session(browser: Browser, avatar: 'on' | 'off', wavs: string[]) {
  const context = await browser.newContext({ permissions: ['microphone'], viewport: { width: 1440, height: 900 } })
  await context.addInitScript({ content: fakeMicrophone(avatar) })
  const page = await context.newPage()
  await page.goto('/live?measure')
  if (avatar === 'on') {
    await expect(page.locator('[data-avatar="ready"]'), 'the avatar should load (it fell back to the orb)').toBeVisible({
      timeout: 60_000,
    })
  }
  await ask(page, wavs[0]) // warm-up, not counted: the first transcription loads Whisper
  const rows: (Utterance | null)[] = []
  for (const [i, wav] of wavs.entries()) {
    rows.push(await ask(page, wav))
    console.log(`avatar ${avatar} ${i + 1}/${wavs.length}: ${rows.at(-1)?.ttfa.toFixed(0) ?? 'no answer'} ms`)
  }
  await context.close()
  return rows
}

/** The avatar from a cold cache: until its first frame (from navigation), and the model's
 * download and parse alone. */
async function loads(browser: Browser) {
  const firstFrame: number[] = []
  const model: number[] = []
  for (let i = 0; i < LOADS; i++) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
    await context.addInitScript({ content: fakeMicrophone('on') })
    const page = await context.newPage()
    await page.goto('/live?measure')
    await page.waitForFunction(`'avatar-first-frame' in window.__probe.peek().marks`, undefined, { timeout: 60_000 })
    const marks = (await page.evaluate('window.__probe.peek().marks')) as Record<string, number>
    firstFrame.push(marks['avatar-first-frame'])
    model.push(marks['avatar-loaded'] - marks['avatar-load-start'])
    await context.close()
  }
  return { first_frame_ms: spread(firstFrame), model_ms: spread(model) }
}

const git = () => {
  const sha = execSync('git rev-parse --short HEAD').toString().trim()
  return execSync('git status --porcelain').toString().trim() ? `${sha}-dirty` : sha
}

const stamp = (d: Date) => {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`
}

test('voice measurements', async ({ browser }) => {
  test.setTimeout(0)
  const questions = QUESTIONS.slice(0, UTTERANCES)
  const wavs = await Promise.all(questions.map(speech))
  const custom = await fetch('http://localhost:5173/avatar/shelfwise.vrm', { method: 'HEAD' })
  const own = custom.ok && !(custom.headers.get('content-type') ?? '').startsWith('text/')

  // Asking a question again finds warmer caches (the LLM's prompt, the search's lazy loads), so
  // the order is balanced: the first half avatar off then on, the second half on then off.
  const half = Math.ceil(wavs.length / 2)
  const offFirst = await session(browser, 'off', wavs.slice(0, half))
  const onFirst = await session(browser, 'on', wavs.slice(0, half))
  const onSecond = await session(browser, 'on', wavs.slice(half))
  const offSecond = await session(browser, 'off', wavs.slice(half))
  const off = [...offFirst, ...offSecond]
  const on = [...onFirst, ...onSecond]
  const created = new Date()
  const parsers = [...new Set([...off, ...on].flatMap((u) => (u?.parser ? [u.parser] : [])))]
  const report = {
    created: created.toISOString(),
    git: git(),
    kind: 'voice',
    questions,
    parser: parsers.join(', ') || null,
    browser: `Chromium ${browser.version()}`,
    machine: `${cpus()[0]?.model ?? '?'}, ${Math.round(totalmem() / 2 ** 30)} GB`,
    avatar_model: own ? 'shelfwise.vrm' : 'sample.vrm',
    conditions: { off: summarise(off), on: summarise(on) },
    avatar_cost_ms: pairedTtfa(off, on),
    avatar_load: await loads(browser),
    rows: { off, on },
  }
  mkdirSync(REPORTS, { recursive: true })
  const file = `${REPORTS}${stamp(created)}_${report.git}_voice.json`
  writeFileSync(file, `${JSON.stringify(report, null, 2)}\n`)
  console.log(`\n${file}\n${JSON.stringify({ ...report.conditions, avatar_cost_ms: report.avatar_cost_ms, avatar_load: report.avatar_load }, null, 2)}`)
  expect(report.conditions.on.answered, 'most questions should get a spoken answer').toBeGreaterThan(questions.length / 2)
})
