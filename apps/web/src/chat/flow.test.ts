import { describe, expect, it } from 'vitest'

import { placement, VISIBLE } from './flow'

describe('cover flow placement', () => {
  it('stands the focus in front, facing the reader', () => {
    expect(placement(0)).toEqual({ transform: 'translate3d(-50%, 0, 60px)', zIndex: 20 })
  })

  it('angles the others toward the middle, mirrored on each side, further back the further away', () => {
    const left = placement(-1)
    const right = placement(1)
    expect(left.transform).toContain('rotateY(50deg)')
    expect(right.transform).toContain('rotateY(-50deg)')
    expect(Number(placement(2).zIndex)).toBeLessThan(Number(right.zIndex))
    expect(Number(placement(3).opacity)).toBeLessThan(Number(placement(1).opacity))
  })

  it('hides books beyond the visible few, and they take no clicks', () => {
    expect(placement(VISIBLE + 1)).toMatchObject({ opacity: 0, pointerEvents: 'none' })
    expect(placement(VISIBLE).pointerEvents).toBeUndefined()
  })
})
