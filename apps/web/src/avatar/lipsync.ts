// Lip-sync from the speech audio itself: loudness opens the mouth, and the
// balance of energy across the frequency bands picks the vowel shape. Vowels differ mostly
// in their first two formants: "oo"/"oh" sit low, "ah" in the middle, "ee"/"ih" put energy
// high. A heuristic, not phoneme recognition, but cheap and in sync by construction: it reads
// the same samples the speakers play.

export type Viseme = 'aa' | 'ih' | 'ou' | 'ee' | 'oh'
export type Visemes = Record<Viseme, number>

export const VISEMES: Viseme[] = ['aa', 'ih', 'ou', 'ee', 'oh']
export const CLOSED: Visemes = { aa: 0, ih: 0, ou: 0, ee: 0, oh: 0 }

export interface Bands {
  low: number // 200-800 Hz: first formant of rounded vowels
  mid: number // 800-1800 Hz: open vowels
  high: number // 1800-3500 Hz: second formant of front vowels
}

export const QUIET = 0.015 // RMS below this is silence
const LOUD = 0.08 // RMS at which the mouth is fully open (Kokoro speaks at ~0.05-0.1)
const SHARPEN = 3 // power on the vowel scores: one clear shape, not a blur of all five

/** Mean magnitude (0..1) per band from an AnalyserNode's byte frequency data. */
export function bands(frequency: Uint8Array, sampleRate: number): Bands {
  const hzPerBin = sampleRate / 2 / frequency.length
  const mean = (from: number, to: number) => {
    const a = Math.floor(from / hzPerBin)
    const b = Math.min(frequency.length, Math.floor(to / hzPerBin)) // [from, to): bands share no bin
    let sum = 0
    for (let i = a; i < b; i++) sum += frequency[i]
    return b > a ? sum / (b - a) / 255 : 0
  }
  return { low: mean(200, 800), mid: mean(800, 1800), high: mean(1800, 3500) }
}

/** RMS of time-domain samples in [-1, 1]. */
export function loudness(samples: Float32Array): number {
  let sum = 0
  for (const s of samples) sum += s * s
  return Math.sqrt(sum / Math.max(samples.length, 1))
}

/** Target mouth shape for one frame: weights sum to how open the mouth is. */
export function visemes(volume: number, b: Bands): Visemes {
  const open = Math.min(1, Math.max(0, (volume - QUIET) / (LOUD - QUIET)))
  if (open === 0) return { ...CLOSED }
  const total = b.low + b.mid + b.high || 1
  const low = b.low / total
  const mid = b.mid / total
  const high = b.high / total
  const raw: Visemes = {
    aa: mid * 1.2,
    oh: low * mid * 2.5,
    ou: low * low * 1.5,
    ee: high * 1.6,
    ih: high * mid * 2,
  }
  for (const v of VISEMES) raw[v] = raw[v] ** SHARPEN
  const sum = VISEMES.reduce((s, v) => s + raw[v], 0) || 1
  return Object.fromEntries(VISEMES.map((v) => [v, (raw[v] / sum) * open])) as Visemes
}

const ATTACK_S = 0.04 // the mouth opens fast...
const RELEASE_S = 0.09 // ...and closes a little slower, so it doesn't flutter

/** One frame of smoothing toward `target` (exponential, frame-rate independent). */
export function smooth(current: Visemes, target: Visemes, dt: number): Visemes {
  const out = { ...current }
  for (const v of VISEMES) {
    const tau = target[v] > current[v] ? ATTACK_S : RELEASE_S
    out[v] = current[v] + (target[v] - current[v]) * (1 - Math.exp(-dt / tau))
  }
  return out
}
