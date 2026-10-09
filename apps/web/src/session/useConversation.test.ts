import { act, renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { ClientMessage } from '../api/types'
import { useConversation } from './useConversation'

const sent: ClientMessage[] = []
let startSession: (id: string) => void = () => {}

vi.mock('../api/client', () => ({
  startSession: () => new Promise<string>((resolve) => (startSession = resolve)),
  endSession: () => Promise.resolve(),
  socketUrl: (id: string) => `ws://test/${id}`,
}))
vi.mock('./socket', () => ({
  SessionSocket: class {
    send(message: ClientMessage) {
      sent.push(message)
    }
    connect() {}
    close() {}
  },
}))

describe('useConversation', () => {
  it('keeps a question asked before the session exists and sends it once it does', async () => {
    const { result } = renderHook(() => useConversation())

    act(() => result.current.ask('gothic horror'))
    expect(sent).toEqual([])
    await act(async () => startSession('s1'))

    await waitFor(() => expect(sent).toEqual([{ type: 'text', text: 'gothic horror' }]))
  })
})
