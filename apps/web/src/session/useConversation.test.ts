import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ClientMessage } from '../api/types'
import { useConversation } from './useConversation'

const sent: ClientMessage[] = []
const sentTo: string[] = [] // the socket URL each message went to
const ended: string[] = []
const starts: ((id: string) => void)[] = [] // pending session starts, oldest first
let startSession: (id: string) => void = () => {}

vi.mock('../api/client', () => ({
  startSession: () =>
    new Promise<string>((resolve) => {
      starts.push(resolve)
      startSession = resolve
    }),
  endSession: (id: string) => {
    ended.push(id)
    return Promise.resolve()
  },
  socketUrl: (id: string) => `ws://test/${id}`,
}))
vi.mock('./socket', () => ({
  SessionSocket: class {
    url: string
    constructor(url: string) {
      this.url = url
    }
    send(message: ClientMessage) {
      sent.push(message)
      sentTo.push(this.url)
    }
    connect() {}
    close() {}
  },
}))

beforeEach(() => {
  sent.length = 0
  sentTo.length = 0
  ended.length = 0
  starts.length = 0
})

describe('useConversation', () => {
  it('keeps a question asked before the session exists and sends it once it does', async () => {
    const { result } = renderHook(() => useConversation())

    act(() => result.current.ask('gothic horror'))
    expect(sent).toEqual([])
    await act(async () => startSession('s1'))

    await waitFor(() => expect(sent).toEqual([{ type: 'text', text: 'gothic horror' }]))
  })

  it('ignores a session that finishes starting after the page moved on, so every message goes to one session', async () => {
    const first = renderHook(() => useConversation())
    first.unmount() // React's development double mount: the first start is abandoned...
    const { result } = renderHook(() => useConversation())
    const [stale, fresh] = starts

    await act(async () => fresh('new'))
    act(() => result.current.ask('thrillers under 300 pages'))
    await act(async () => stale('old')) // ...and finishes last
    act(() => result.current.removeChip({ field: 'pages', label: 'under 300 pages' } as never))

    await waitFor(() => expect(sent.map((m) => m.type)).toEqual(['text', 'remove_chip']))
    expect(sentTo).toEqual(['ws://test/new', 'ws://test/new'])
    expect(ended).toEqual(['old'])
  })
})
