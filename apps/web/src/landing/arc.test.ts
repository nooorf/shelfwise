import { describe, expect, it } from 'vitest'

import { COVER, layout, order } from './arc'

describe('arc layout', () => {
  const arc = layout(1440, 820, 48)
  const shelf = arc.places.filter((p) => p.side === 0)
  const right = arc.places.filter((p) => p.side === 1)
  const left = arc.places.filter((p) => p.side === -1)

  it('puts five small, flat books on the far shelf, centred', () => {
    expect(shelf).toHaveLength(5)
    expect(shelf.every((p) => p.turn === 0 && p.scale === arc.shelf.scale)).toBe(true)
    expect(shelf[2].x).toBeCloseTo(0)
    expect(Math.abs(shelf[0].x)).toBeLessThan(arc.shelf.width / 2)
  })

  it('mirrors the walls: each book nearer, larger and more turned than the last', () => {
    expect(left.map((p) => -p.x)).toEqual(right.map((p) => p.x))
    expect(left.map((p) => -p.turn)).toEqual(right.map((p) => p.turn))
    for (let i = 1; i < right.length; i++) {
      expect(right[i].x).toBeGreaterThan(right[i - 1].x)
      expect(right[i].scale).toBeGreaterThan(right[i - 1].scale)
      expect(Math.abs(right[i].turn)).toBeGreaterThanOrEqual(Math.abs(right[i - 1].turn))
    }
    expect(right[0].x).toBeGreaterThan(arc.shelf.width / 2)
  })

  it('stops the walls at the edge of the screen, cropping only the last books', () => {
    const outer = right[right.length - 1]
    const seen = COVER.w * outer.scale * Math.cos((outer.turn * Math.PI) / 180)
    expect(outer.x - seen / 2).toBeLessThanOrEqual(720)
    expect(right.length).toBeGreaterThanOrEqual(4)
  })

  it('uses only the books there are, a pair at a time on the walls', () => {
    expect(layout(1440, 820, 2).places).toHaveLength(2)
    expect(layout(1440, 820, 8).places).toHaveLength(7) // five on the shelf, one pair
    expect(layout(1440, 820, 0).places).toEqual([])
  })

  it('keeps three on the shelf on a phone', () => {
    expect(layout(390, 800, 48).places.filter((p) => p.side === 0)).toHaveLength(3)
  })

  it('reads left to right', () => {
    const xs = order(arc.places).map((i) => arc.places[i].x)
    expect(xs).toEqual([...xs].sort((a, b) => a - b))
  })
})
