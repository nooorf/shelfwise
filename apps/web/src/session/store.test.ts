import { beforeEach, describe, expect, it } from 'vitest'

import { book, turn } from '../test/fixtures'
import { useSession } from './store'

const reply = { intro: 'Two picks.', items: [{ work_id: 1, why: 'Tense.', source: 'llm' as const }],
  follow_up: '', source: 'llm' as const, problems: [], attempts: 1, ms: 10 }

describe('session store', () => {
  beforeEach(() => {
    useSession.setState({ exchanges: [], shelf: null, shelfReply: null, status: 'ready', error: null })
  })

  it('shows cards first, then the reply, then is ready again', () => {
    const { said, receive } = useSession.getState()
    said('thrillers')
    expect(useSession.getState().status).toBe('searching')

    receive({ type: 'turn', ...turn(1) })
    expect(useSession.getState().status).toBe('writing')
    expect(useSession.getState().shelf?.results).toHaveLength(2)
    expect(useSession.getState().exchanges[0].turn).toBe(1)

    receive({ type: 'reply', turn: 1, reply })
    receive({ type: 'done', turn: 1 })
    const state = useSession.getState()
    expect(state.shelfReply?.intro).toBe('Two picks.')
    expect(state.status).toBe('ready')
    expect(state.exchanges[0].pending).toBe(false)
  })

  it('small talk leaves the shelf alone; start over clears it', () => {
    const { said, receive } = useSession.getState()
    said('thrillers')
    receive({ type: 'turn', ...turn(1) })
    said('hi')
    receive({ type: 'turn', ...turn(2, { route: 'chat', kind: 'chat', results: [] }) })
    expect(useSession.getState().shelf?.turn).toBe(1)

    said('start over')
    receive({ type: 'turn', ...turn(3, { route: 'start_over', kind: 'start_over', results: [] }) })
    expect(useSession.getState().shelf).toBeNull()
  })

  it('a reply for an older turn never lands on the newer shelf', () => {
    const { said, receive } = useSession.getState()
    said('thrillers')
    receive({ type: 'turn', ...turn(1) })
    said('mysteries')
    receive({ type: 'turn', ...turn(2, { results: [book(3)] }) })
    receive({ type: 'reply', turn: 1, reply })
    expect(useSession.getState().shelfReply).toBeNull()
  })

  it('cancelled and failed turns stop waiting', () => {
    const { said, receive } = useSession.getState()
    said('thrillers')
    receive({ type: 'turn', ...turn(1) })
    receive({ type: 'cancelled', turn: 1 })
    expect(useSession.getState().exchanges[0]).toMatchObject({ cancelled: true, pending: false })

    said('???')
    receive({ type: 'error', message: 'session expired' })
    expect(useSession.getState().error).toBe('session expired')
    expect(useSession.getState().exchanges.every((e) => !e.pending)).toBe(true)
  })
})
