import { describe, expect, it } from 'vitest'

import { bands, CLOSED, loudness, smooth, visemes } from './lipsync'

const sum = (v: Record<string, number>) => Object.values(v).reduce((a, b) => a + b, 0)

describe('lip-sync', () => {
  it('measures bands from analyser bins', () => {
    const bins = new Uint8Array(1024) // 24 kHz: ~11.7 Hz per bin
    bins.fill(255, Math.floor(200 / 11.71875), Math.floor(800 / 11.71875))
    const b = bands(bins, 24_000)
    expect(b.low).toBeCloseTo(1, 1)
    expect(b.mid).toBe(0)
    expect(b.high).toBe(0)
  })

  it('stays closed in silence and opens with loudness', () => {
    const b = { low: 0.2, mid: 0.6, high: 0.2 }
    expect(visemes(0.005, b)).toEqual(CLOSED)
    expect(sum(visemes(0.06, b))).toBeCloseTo(0.69, 2)
    expect(sum(visemes(0.5, b))).toBeCloseTo(1)
    expect(loudness(new Float32Array([0.5, -0.5]))).toBeCloseTo(0.5)
  })

  it('picks the vowel from where the energy is', () => {
    const top = (b: { low: number; mid: number; high: number }) => {
      const v = visemes(0.5, b)
      return (Object.keys(v) as (keyof typeof v)[]).sort((x, y) => v[y] - v[x])[0]
    }
    expect(top({ low: 0.1, mid: 0.8, high: 0.1 })).toBe('aa')
    expect(top({ low: 0.1, mid: 0.2, high: 0.7 })).toBe('ee')
    expect(top({ low: 0.9, mid: 0.05, high: 0.05 })).toBe('ou')
    const ah = visemes(0.5, { low: 0.1, mid: 0.8, high: 0.1 })
    expect(ah.aa).toBeGreaterThan(0.6) // one clear shape, not a blur
  })

  it('opens faster than it closes, independent of frame rate', () => {
    const open = { ...CLOSED, aa: 1 }
    const opened = smooth(CLOSED, open, 1 / 60)
    const closed = smooth(open, CLOSED, 1 / 60)
    expect(opened.aa).toBeGreaterThan(1 - closed.aa)
    const twoSteps = smooth(smooth(CLOSED, open, 1 / 120), open, 1 / 120)
    expect(twoSteps.aa).toBeCloseTo(opened.aa, 5)
  })
})
