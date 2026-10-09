import { describe, expect, it } from 'vitest'

import { BARGE_IN_RMS, frameLevel } from './useConversation'

const frame = (amplitude: number) => new Int16Array(512).fill(Math.round(amplitude * 32767)).buffer

describe('barge-in gate', () => {
  it('lets a person talking through and keeps leaked playback out', () => {
    expect(frameLevel(frame(0.1))).toBeCloseTo(0.1, 3)
    expect(frameLevel(frame(0.1))).toBeGreaterThan(BARGE_IN_RMS) // someone at the kiosk
    expect(frameLevel(frame(0.01))).toBeLessThan(BARGE_IN_RMS) // echo-cancelled residue
  })
})
