import { describe, expect, it } from 'vitest'

import type { Log, LogFrame } from './voice-stats.ts'
import { avOffset, fps, meanCi, pairedTtfa, percentile, STAGES, summarise, utterance } from './voice-stats.ts'

// Spoken until t=1000; transcript 900 ms later (300 of it Whisper); the turn 50 ms after that
// (parse 20 + retrieve 20 + 10 handing over); the first clip 200 ms later (150 synthesis), heard
// 100 ms after it arrived. Time to first audio: 1250 ms.
function log(frames: LogFrame[] = []): Log {
  return {
    events: [
      { type: 'speech_start', t: 400 },
      { type: 'transcript', t: 1900, ms: 300 },
      { type: 'turn', t: 1950, turn: 2, timings: { parse: 20, retrieve: 20, narrate: 0, total: 40 }, parser: 'cascade' },
      { type: 'audio', t: 2150, turn: 2, ms: 150 },
      { type: 'reply_piece', t: 4000, turn: 2, kind: 'intro' },
      { type: 'reply_piece', t: 5000, turn: 2, kind: 'item' },
      { type: 'done', t: 6000, turn: 2 },
    ],
    clips: [
      { turn: 2, heard: 2250, duration: 1000 },
      { turn: 2, heard: 3250, duration: 1000 },
    ],
    frames,
    marks: {},
  }
}

const frames = (from: number, to: number, every: number, open: (t: number) => number): LogFrame[] =>
  Array.from({ length: Math.floor((to - from) / every) + 1 }, (_, i) => {
    const t = from + i * every
    return { t, open: open(t), speaking: true }
  })

describe('one utterance', () => {
  it('splits the time to first audio into stages that add up to it', () => {
    const u = utterance(log(), 1000)!
    expect(u.ttfa).toBe(1250)
    expect(u.stages).toEqual({ endpoint: 600, transcribe: 300, parse: 20, retrieve: 20, voice: 150, playback: 100, handoffs: 60 })
    expect(STAGES.reduce((sum, s) => sum + u.stages[s], 0)).toBe(u.ttfa)
    expect(u.first_note).toBe(4000) // the first book note, not the intro
    expect(u.parser).toBe('cascade')
  })

  it('is null when the answer never made a sound', () => {
    const silent = { ...log(), clips: [] }
    expect(utterance(silent, 1000)).toBeNull()
  })

  it('measures the lips against the sound, and the frame rate while speaking', () => {
    const u = utterance(log(frames(2000, 4250, 16, (t) => (t >= 2282 ? 0.5 : 0))), 1000)!
    expect(u.av_offset).toBe(2288 - 2250) // the first frame at or past the opening
    expect(u.fps).toBeCloseTo(62.5, 0)
  })
})

describe('lip-sync offset', () => {
  it('can be negative: the mouth may move before the speakers play', () => {
    expect(avOffset(frames(2000, 2400, 16, (t) => (t >= 2210 ? 1 : 0)), 2250)).toBe(2224 - 2250)
  })

  it('is null without avatar frames', () => {
    expect(avOffset([], 2250)).toBeNull()
    expect(fps([])).toBeNull()
  })
})

describe('summary', () => {
  it('percentiles interpolate', () => {
    expect(percentile([1, 2, 3, 4], 50)).toBe(2.5)
    expect(percentile([10], 95)).toBe(10)
  })

  it('counts questions without an answer, and pairs avatar on against off', () => {
    const a = utterance(log(), 1000)
    const b = utterance(log(), 900) // 100 ms slower
    const s = summarise([a, null, b])
    expect([s.questions, s.answered]).toEqual([3, 2])
    expect(s.ttfa?.mean).toBe(1300)
    expect(s.stages?.endpoint).toBe(650)
    expect(s.av_offset).toBeNull()
    expect(pairedTtfa([a, b], [b, null])).toEqual({ n: 1, mean: 100, p50: 100, p95: 100, ci95: [100, 100] })
  })

  it('puts a confidence interval around the mean that covers it, the same every time', () => {
    const values = [-900, 400, 1200, -300, 800, 50, -1500, 2000]
    const [low, high] = meanCi(values)
    expect(low).toBeLessThan(218.75)
    expect(high).toBeGreaterThan(218.75)
    expect(meanCi(values)).toEqual([low, high])
  })
})
