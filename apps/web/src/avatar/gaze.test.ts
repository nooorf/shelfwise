import { describe, expect, it } from 'vitest'

import { aim, approach, browsed, FOLLOW_S, GLANCE_S, gazeTarget, LIMITS, rise } from './gaze'

const BOOKS = [
  { x: 100, y: 400 },
  { x: 300, y: 420 },
  { x: 500, y: 430 },
  { x: 700, y: 420 },
  { x: 900, y: 400 },
]

describe('gaze target', () => {
  it('follows a moving cursor, then goes back to browsing the books', () => {
    const cursor = { x: 120, y: 80, at: 10 }
    expect(gazeTarget(10.5, cursor, BOOKS, null)).toEqual({ x: 120, y: 80, mode: 'cursor' })
    expect(gazeTarget(10 + FOLLOW_S + 0.01, cursor, BOOKS, null)?.mode).toBe('browse')
    expect(gazeTarget(3, null, BOOKS, null)?.mode).toBe('browse')
  })

  it('looks at a book someone points at, even while the cursor moves', () => {
    const cursor = { x: 120, y: 80, at: 10 }
    expect(gazeTarget(10.1, cursor, BOOKS, BOOKS[3])).toEqual({ ...BOOKS[3], mode: 'book' })
  })

  it('has nothing to look at before the books and the cursor', () => {
    expect(gazeTarget(3, null, [], null)).toBeNull()
  })

  it('rests on one book at a time and hops across the arc, visiting them all', () => {
    expect(browsed(0, 5)).toBe(browsed(GLANCE_S * 0.9, 5))
    const seen = Array.from({ length: 5 }, (_, i) => browsed(GLANCE_S * i + 0.1, 5))
    expect(new Set(seen).size).toBe(5)
    expect(Math.abs(seen[1] - seen[0])).toBeGreaterThan(1)
  })
})

it('rise goes from hidden to up, overshooting on the way', () => {
  expect(rise(0, 1, 1)).toBeCloseTo(0)
  expect(rise(2.5, 1, 1)).toBeCloseTo(1)
  const samples = Array.from({ length: 20 }, (_, i) => rise(1 + i / 20, 1, 1))
  expect(Math.max(...samples)).toBeGreaterThan(1)
})

describe('aim', () => {
  const head = { x: 0, y: 1.5, z: 0 }

  it('turns toward +x and tilts up for a target up and to the right', () => {
    const { yaw, pitch } = aim(head, { x: 0.3, y: 1.7, z: 1 })
    expect(yaw).toBeGreaterThan(0)
    expect(pitch).toBeGreaterThan(0)
  })

  it('stays within what a neck can do, even for a target behind', () => {
    expect(aim(head, { x: -5, y: 1.5, z: 0.1 }).yaw).toBe(-LIMITS.yaw)
    expect(aim(head, { x: 0, y: -3, z: 1 }).pitch).toBe(-LIMITS.down)
    expect(aim(head, { x: 0, y: 9, z: 1 }).pitch).toBe(LIMITS.up)
    expect(Math.abs(aim(head, { x: 0.1, y: 1.5, z: -2 }).yaw)).toBeLessThanOrEqual(LIMITS.yaw)
  })
})

it('approach eases the same at any frame rate', () => {
  const once = approach(0, 1, 0.1, 0.25)
  let twice = approach(0, 1, 0.05, 0.25)
  twice = approach(twice, 1, 0.05, 0.25)
  expect(twice).toBeCloseTo(once)
})
