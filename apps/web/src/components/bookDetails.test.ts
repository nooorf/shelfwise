import { describe, expect, it } from 'vitest'

import { copyLine, tagLines } from './bookDetails'

describe('book details in words', () => {
  it('words the tags it knows and skips unknown ones', () => {
    expect(
      tagLines({ darkness: 2, romance: null, pace: 'fast', audience: 'ya', fiction: true,
                 historical_setting: 'yes', setting_period: 'Victorian London' }),
    ).toEqual([
      ['Tone', 'Dark'], ['Pace', 'Fast'], ['For', 'Teens (YA)'], ['Kind', 'Fiction'],
      ['Set in', 'Victorian London'],
    ])
  })

  it('says where a copy is and when a borrowed one is back', () => {
    const where = { branch: 'Main', floor: '2', call_number: 'FIC FLY' }
    expect(copyLine({ ...where, status: 'available', due_date: null })).toBe(
      'On the shelf — Main · Floor 2 · FIC FLY',
    )
    expect(
      copyLine({ ...where, status: 'on_loan', due_date: '2026-10-30' }, new Date(2026, 9, 9)),
    ).toBe('Borrowed, due back 30 Oct — Main · Floor 2 · FIC FLY')
  })
})
