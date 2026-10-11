import { describe, expect, it } from 'vitest'

import { fanPlace } from './fan'

describe('fan placement', () => {
  it('centres the fan, mirrored, dropping and turning toward the ends', () => {
    expect(fanPlace(2, 5)).toEqual({ x: 0, y: 0, turn: 0 })
    const [left, right] = [fanPlace(0, 5), fanPlace(4, 5)]
    expect(left.x).toBe(-right.x)
    expect(left.y).toBe(right.y)
    expect(left.y).toBeGreaterThan(fanPlace(1, 5).y)
    expect(left.turn).toBeLessThan(0)
    expect(right.turn).toBeGreaterThan(0)
  })

  it('has no middle book for an even count, but stays centred', () => {
    expect(fanPlace(0, 2).x).toBe(-fanPlace(1, 2).x)
  })
})
