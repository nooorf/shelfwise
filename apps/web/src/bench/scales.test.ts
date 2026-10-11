import { describe, expect, it } from 'vitest'

import { logScale, logTicks, niceStep, paretoFront, step, waterfall } from './scales'

describe('bench scales', () => {
  it('finds the systems nothing beats on both quality and speed', () => {
    const systems = [
      { name: 'bm25', q: 0.41, ms: 6 }, { name: 'bm25_raw', q: 0.39, ms: 0.3 },
      { name: 'dense', q: 0.65, ms: 32 }, { name: 'hybrid', q: 0.59, ms: 11 },
      { name: 'hybrid_lookup', q: 0.6, ms: 129 }, { name: 'parsed', q: 0.69, ms: 147 },
    ]
    const front = paretoFront(systems, (s) => s.q, (s) => s.ms).map((s) => s.name)
    expect(front).toEqual(['bm25_raw', 'bm25', 'hybrid', 'dense', 'parsed'])
  })

  it('maps latencies on a log scale with decade ticks', () => {
    const x = logScale(0.1, 1000, 0, 400)
    expect(x(0.1)).toBe(0)
    expect(x(10)).toBeCloseTo(200)
    expect(x(0.01)).toBe(0) // clamped
    expect(logTicks(0.3, 150)).toEqual([1, 10, 100])
  })

  it('bins scores into sequential steps', () => {
    expect([step(0), step(0.5), step(1), step(1.4), step(-1)]).toEqual([0, 6, 11, 11, 0])
  })

  it('lays stages end to end, a negative one as nothing', () => {
    expect(waterfall(['a', 'b', 'c'], { a: 100, b: -5, c: 50 })).toEqual([
      { key: 'a', start: 0, end: 100 },
      { key: 'b', start: 100, end: 100 },
      { key: 'c', start: 100, end: 150 },
    ])
  })

  it('picks round tick steps', () => {
    expect(niceStep(2300)).toBe(500)
    expect(niceStep(9000)).toBe(2000)
    expect(niceStep(18)).toBe(5)
  })
})
