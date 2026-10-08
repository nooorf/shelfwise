import { describe, expect, it } from 'vitest'

import { book } from '../test/fixtures'
import { availabilityText, dueLabel } from './availability'

const today = new Date('2026-10-08T09:00:00')

describe('availability in words', () => {
  it('says where an available copy is', () => {
    expect(availabilityText(book(1).availability, today)).toBe('Available · Floor 2 · FIC WRI')
  })

  it('says when a borrowed copy comes back', () => {
    expect(availabilityText(book(1, 'x', 'due_soon').availability, today)).toBe('Due back Mon')
    expect(dueLabel('2026-10-30', today)).toBe('Due back 30 Oct')
    expect(dueLabel('2026-10-01', today)).toBe('Due back today') // overdue: no promises
  })
})
