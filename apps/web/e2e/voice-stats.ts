// The voice measurements' arithmetic (measure.voice.ts): one spoken question's probe log
// (src/session/probe.ts) in, its time to first audio split into stages, its lip-sync offset
// and frame rate out; then the summary over all questions. Pure, so it's tested on its own.

// The probe's log, as the page hands it over (the harness has no DOM types).
export interface LogEvent {
  type: string
  t: number
  turn?: number
  ms?: number
  kind?: string
  timings?: Record<string, number>
  parser?: string
}
export interface LogClip {
  turn: number
  heard: number
  duration: number
}
export interface LogFrame {
  t: number
  open: number
  speaking: boolean
}
export interface Log {
  events: LogEvent[]
  clips: LogClip[]
  frames: LogFrame[]
  marks: Record<string, number>
}

/** The stages of a spoken turn, in order: their means add up to the mean time to first audio. */
export const STAGES = ['endpoint', 'transcribe', 'parse', 'retrieve', 'voice', 'playback', 'handoffs'] as const
export type Stage = (typeof STAGES)[number]

export interface Utterance {
  ttfa: number // end of the question's speech -> first sound of the answer from the speakers
  stages: Record<Stage, number>
  first_note: number | null // end of speech -> the LLM's first book note on screen (narration on)
  av_offset: number | null // mouth opening minus sound starting; positive: the lips are late
  fps: number | null // avatar frames per second while it speaks
  parser: string | null
}

export const MOUTH_OPEN = 0.1 // openness at which the mouth counts as open
const LOOK_BACK_MS = 250 // the mouth can open before the sound is heard (output latency)

/** One question, `spokeUntil` being when its last syllable went into the microphone. */
export function utterance(log: Log, spokeUntil: number): Utterance | null {
  const transcript = log.events.find((e) => e.type === 'transcript' && e.t >= spokeUntil)
  const turn = log.events.find((e) => e.type === 'turn' && transcript && e.t >= transcript.t)
  if (!transcript || !turn?.timings) return null
  const audio = log.events.find((e) => e.type === 'audio' && e.turn === turn.turn)
  const clips = log.clips.filter((c) => c.turn === turn.turn)
  if (!audio || clips.length === 0) return null
  const heard = Math.min(...clips.map((c) => c.heard))
  const stt = transcript.ms ?? 0
  const voice = audio.ms ?? 0
  const stages: Record<Stage, number> = {
    endpoint: transcript.t - spokeUntil - stt,
    transcribe: stt,
    parse: turn.timings.parse ?? 0,
    retrieve: turn.timings.retrieve ?? 0,
    voice,
    playback: heard - audio.t,
    handoffs: turn.t - transcript.t - (turn.timings.total ?? 0) + (audio.t - turn.t - voice),
  }
  const note = log.events.find((e) => e.type === 'reply_piece' && e.kind === 'item' && e.turn === turn.turn)
  const end = Math.max(...clips.map((c) => c.heard + c.duration))
  return {
    ttfa: heard - spokeUntil,
    stages,
    first_note: note ? note.t - spokeUntil : null,
    av_offset: avOffset(log.frames, heard),
    fps: fps(log.frames.filter((f) => f.speaking && f.t >= heard && f.t <= end)),
    parser: turn.parser ?? null,
  }
}

/** First frame the mouth is open, minus when the sound started; null without avatar frames. */
export function avOffset(frames: LogFrame[], heard: number): number | null {
  const open = frames.find((f) => f.t >= heard - LOOK_BACK_MS && f.open >= MOUTH_OPEN)
  return open ? open.t - heard : null
}

/** Frames per second over a run of frames; null if too few to tell. */
export function fps(frames: LogFrame[]): number | null {
  if (frames.length < 10) return null
  return ((frames.length - 1) / (frames.at(-1)!.t - frames[0].t)) * 1000
}

export function percentile(values: number[], p: number): number {
  const sorted = [...values].sort((a, b) => a - b)
  const at = (sorted.length - 1) * (p / 100)
  const lo = Math.floor(at)
  const hi = Math.ceil(at)
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (at - lo)
}

const mean = (values: number[]) => values.reduce((s, v) => s + v, 0) / values.length
const r = (v: number) => Math.round(v * 10) / 10

export interface Spread {
  n: number
  mean: number
  p50: number
  p95: number
}

export function spread(values: number[]): Spread | null {
  if (values.length === 0) return null
  return { n: values.length, mean: r(mean(values)), p50: r(percentile(values, 50)), p95: r(percentile(values, 95)) }
}

export interface Condition {
  questions: number // asked
  answered: number // with a first audio measured
  ttfa: Spread | null
  stages: Record<Stage, number> | null // mean ms per stage
  first_note: Spread | null
  av_offset: (Spread & { abs_p95: number }) | null
  fps: Spread | null // per answer; p5 below is the worst answers'
  fps_p5: number | null
}

export function summarise(rows: (Utterance | null)[]): Condition {
  const ok = rows.filter((u): u is Utterance => u !== null)
  const offsets = ok.flatMap((u) => (u.av_offset === null ? [] : [u.av_offset]))
  const rates = ok.flatMap((u) => (u.fps === null ? [] : [u.fps]))
  const offset = spread(offsets)
  return {
    questions: rows.length,
    answered: ok.length,
    ttfa: spread(ok.map((u) => u.ttfa)),
    stages: ok.length
      ? (Object.fromEntries(STAGES.map((s) => [s, r(mean(ok.map((u) => u.stages[s])))])) as Record<Stage, number>)
      : null,
    first_note: spread(ok.flatMap((u) => (u.first_note === null ? [] : [u.first_note]))),
    av_offset: offset && { ...offset, abs_p95: r(percentile(offsets.map(Math.abs), 95)) },
    fps: spread(rates),
    fps_p5: rates.length ? r(percentile(rates, 5)) : null,
  }
}

/** Avatar on minus off, question by question (same questions, same order). */
export function pairedTtfa(off: (Utterance | null)[], on: (Utterance | null)[]): Spread | null {
  const diffs = off.flatMap((u, i) => (u && on[i] ? [on[i].ttfa - u.ttfa] : []))
  return spread(diffs)
}
