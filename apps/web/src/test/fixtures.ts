import type { BookResult, TurnResponse } from '../api/types'

export function book(id: number, title = `Book ${id}`, state = 'available'): BookResult {
  return {
    work_id: id,
    work_key: `97800000000${String(id).padStart(2, '0')}`,
    title,
    subtitle: null,
    authors: ['A. Writer'],
    year: 2019,
    pages: 320,
    genres: ['thriller'],
    availability: {
      state: state as BookResult['availability']['state'],
      available_copies: state === 'available' ? 1 : 0,
      total_copies: 1,
      next_due: state === 'available' ? null : '2026-10-12',
      location: { branch: 'Main', floor: '2', call_number: 'FIC WRI' },
    },
  }
}

export function turn(n: number, overrides: Partial<TurnResponse> = {}): TurnResponse {
  return {
    session_id: 's1',
    turn: n,
    kind: 'new_search',
    route: 'search',
    intent: 'discover',
    parser: 'cascade',
    parse_error: null,
    system: 'parsed_hybrid',
    notes: [],
    chips: [],
    semantic_query: 'thrillers',
    lookup: null,
    seed_titles: [],
    results: [book(1), book(2)],
    reply: null,
    facets: {},
    relaxations: [],
    can_undo: false,
    timings_ms: {},
    ...overrides,
  }
}
