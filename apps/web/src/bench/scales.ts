// Pure helpers for the bench charts, testable without rendering.

export const SHIPPED = 'parsed_hybrid' // the system the app runs

/** Systems no other system beats on both quality (higher) and latency (lower), fastest first. */
export function paretoFront<T>(items: T[], quality: (t: T) => number, ms: (t: T) => number): T[] {
  const byMs = [...items].sort((a, b) => ms(a) - ms(b) || quality(b) - quality(a))
  const front: T[] = []
  let best = -Infinity
  for (const item of byMs) {
    if (quality(item) > best) {
      front.push(item)
      best = quality(item)
    }
  }
  return front
}

/** A log scale from [lo, hi] onto [from, to]; latencies span 0.3 ms to 150 ms. */
export function logScale(lo: number, hi: number, from: number, to: number) {
  const a = Math.log10(lo)
  const b = Math.log10(hi)
  return (v: number) => from + ((Math.log10(Math.max(v, lo)) - a) / (b - a)) * (to - from)
}

/** Round "nice" log ticks inside [lo, hi]: 0.1, 1, 10, 100, ... */
export function logTicks(lo: number, hi: number): number[] {
  const ticks: number[] = []
  for (let p = Math.floor(Math.log10(lo)); p <= Math.ceil(Math.log10(hi)); p++) {
    const v = 10 ** p
    if (v >= lo && v <= hi) ticks.push(v)
  }
  return ticks
}

export const SEQUENTIAL_STEPS = 12 // --color-seq-0 .. 11 in index.css, near zero to high

/** Which sequential step a score in [0, 1] takes. */
export function step(score: number): number {
  return Math.round(Math.min(1, Math.max(0, score)) * (SEQUENTIAL_STEPS - 1))
}

/** Stages that run one after another, as [start, end) offsets from 0, in the order given. */
export function waterfall<K extends string>(order: readonly K[], ms: Record<K, number>) {
  let at = 0
  return order.map((key) => {
    const width = Math.max(0, ms[key])
    const bar = { key, start: at, end: at + width }
    at += width
    return bar
  })
}

/** A tick step of 1, 2 or 5 x 10^n giving about `count` ticks up to `max`. */
export function niceStep(max: number, count = 5): number {
  const raw = max / Math.max(count, 1)
  const power = 10 ** Math.floor(Math.log10(raw))
  return ([1, 2, 5, 10].find((m) => m * power >= raw) ?? 10) * power
}
