import { describe, expect, it } from 'vitest'

import { book, turn } from '../test/fixtures'
import { announcement } from './announce'

describe('announcement', () => {
  it('says the notes, the count and the first titles, then the reply', () => {
    const response = turn(1, {
      notes: ['New search.'],
      results: [book(1, 'Gone Girl'), book(2, 'Rebecca'), book(3, 'Sharp Objects'), book(4)],
    })
    const e = { key: 1, said: 'thrillers', turn: 1, response, pending: true }

    expect(announcement(e)).toBe('New search. 4 books: Gone Girl; Rebecca; Sharp Objects; and more.')
    const reply = { intro: 'Four on the shelf now.', items: [], follow_up: '', source: 'llm' as const,
                    attempts: 1, ms: 900 }
    expect(announcement({ ...e, reply })).toContain('and more. Four on the shelf now.')
  })

  it('says waiting, stopped, or only the notes for chat', () => {
    expect(announcement({ key: 1, said: 'hi', pending: true })).toBe('Looking…')
    expect(announcement({ key: 1, said: 'hi', pending: false, cancelled: true })).toBe('Stopped.')
    const chat = turn(1, { route: 'chat', notes: ['I can help you find books.'] })
    expect(announcement({ key: 1, said: 'hi', response: chat, pending: false })).toBe(
      'I can help you find books.',
    )
    expect(announcement(undefined)).toBe('')
  })
})
