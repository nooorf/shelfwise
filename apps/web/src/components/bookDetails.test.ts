import { describe, expect, it } from 'vitest'

import { copyLine, shortTitle, tagLines } from './bookDetails'

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

  it('drops a subtitle for one-line captions, unless the head is too short', () => {
    expect(shortTitle('Wicked: The Life and Times of the Wicked Witch of the West')).toBe('Wicked')
    expect(shortTitle('Death Note, Vol. 1: Boredom')).toBe('Death Note, Vol. 1')
    expect(shortTitle('Y: The Last Man')).toBe('Y: The Last Man')
    expect(shortTitle('Pines')).toBe('Pines')
  })
})
