// Timing probe for the voice measurements (`make measure`, apps/web/e2e/measure.voice.ts). Off
// unless the page was opened with ?measure: then it records, on the page's own clock
// (performance.now(), ms), when each server event arrived, when each clip's first sound left
// the speakers, and every avatar frame with how open the mouth was. The harness reads the log
// with window.__probe.peek() and clears it with take(). Off, every call is a single check.
import type { ServerEvent } from '../api/types'
import { QUIET } from '../avatar/lipsync'

export interface ProbeEvent {
  type: string
  t: number
  turn?: number
  seq?: number
  ms?: number // the server's own time for it: transcription, or one clip's synthesis
  kind?: string // reply_piece: intro, item or follow_up
  timings?: Record<string, number> // turn: parse, retrieve, narrate, total
  parser?: string
}

export interface ProbeClip {
  turn: number
  heard: number // when the clip's first sound (not its leading silence) reaches the speakers
  duration: number // ms
}

export interface ProbeFrame {
  t: number
  open: number // mouth openness, 0-1
  speaking: boolean
}

export interface ProbeLog {
  events: ProbeEvent[]
  clips: ProbeClip[]
  frames: ProbeFrame[]
  marks: Record<string, number>
}

const empty = (): ProbeLog => ({ events: [], clips: [], frames: [], marks: {} })

const on = typeof location !== 'undefined' && new URLSearchParams(location.search).has('measure')
let log = empty()

if (on) {
  ;(globalThis as { __probe?: unknown }).__probe = {
    peek: (): ProbeLog => log,
    take: (): ProbeLog => {
      const out = log
      log = { ...empty(), marks: out.marks } // marks are once per page: kept
      return out
    },
  }
}

export const probe = {
  enabled: on,

  event(event: ServerEvent): void {
    if (!on) return
    const entry: ProbeEvent = { type: event.type, t: performance.now() }
    if ('turn' in event) entry.turn = event.turn
    if (event.type === 'audio') Object.assign(entry, { seq: event.seq, ms: event.ms })
    if (event.type === 'transcript') entry.ms = event.ms
    if (event.type === 'reply_piece') entry.kind = event.kind
    if (event.type === 'turn') Object.assign(entry, { timings: event.timings_ms, parser: event.parser })
    log.events.push(entry)
  },

  clip(clip: ProbeClip): void {
    if (on) log.clips.push(clip)
  },

  frame(open: number, speaking: boolean): void {
    if (on) log.frames.push({ t: performance.now(), open, speaking })
  },

  /** A once-per-page moment (avatar-load-start, avatar-loaded, avatar-first-frame). */
  mark(name: string): void {
    if (on && !(name in log.marks)) log.marks[name] = performance.now()
  },
}

/** Seconds into `buffer` where sound starts: the first 10 ms window loud enough to open the
 * mouth. */
export function onset(buffer: AudioBuffer): number {
  const samples = buffer.getChannelData(0)
  const step = Math.max(1, Math.round(buffer.sampleRate * 0.01))
  for (let i = 0; i + step <= samples.length; i += step) {
    let sum = 0
    for (let j = i; j < i + step; j++) sum += samples[j] * samples[j]
    if (Math.sqrt(sum / step) > QUIET) return i / buffer.sampleRate
  }
  return 0
}
