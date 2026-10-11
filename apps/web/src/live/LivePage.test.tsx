import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Reply } from '../api/types'
import { useSession } from '../session/store'
import { book, turn } from '../test/fixtures'
import { LivePage } from './LivePage'

const conversation = {
  ask: vi.fn(), undo: vi.fn(), removeChip: vi.fn(), switchChip: vi.fn(), feedback: vi.fn(),
  surprise: vi.fn(), explore: vi.fn(), filter: vi.fn(), cancel: vi.fn(),
  listen: vi.fn(), toggleHandsFree: vi.fn(), newVisitor: vi.fn(async () => {}),
}
const options: unknown[] = []

vi.mock('../session/useConversation', () => ({
  useConversation: (o: unknown) => {
    options.push(o)
    return conversation
  },
  micLevel: () => 0,
  speech: { analyser: null, sampleRate: 24000 },
}))

const reply: Reply = {
  intro: 'Two gothic ones.', items: [], follow_up: 'Older, or newer?', source: 'llm', problems: [], attempts: 1, ms: 10,
}

beforeEach(() => {
  vi.clearAllMocks()
  options.length = 0
  vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 404 }))) // no avatar model
  useSession.setState({ exchanges: [], shelf: null, status: 'ready', playing: false, listening: false, error: null, speakOn: null })
})

afterEach(() => vi.unstubAllGlobals())

describe('live page', () => {
  it('is voice only: always spoken answers, no text box, one microphone', async () => {
    render(<LivePage />)
    expect(options[0]).toEqual({ speech: true })
    expect(screen.queryByRole('textbox')).toBeNull()
    expect(screen.getByText('Ask me for a book, out loud.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Type instead' })).toHaveAttribute('href', '/chat')

    await userEvent.click(screen.getByRole('button', { name: 'Speak' }))
    expect(conversation.listen).toHaveBeenCalled()
  })

  it('shows what was heard, the answer as a caption, and the books numbered on the fan', async () => {
    render(<LivePage />)
    act(() =>
      useSession.setState({
        exchanges: [{
          key: 1, said: 'gothic horror please', turn: 1, pending: false, reply,
          fixed: [{ heard: 'shirley jackson', catalog: 'Shirley Jackson' }],
          response: turn(1, { results: [book(1, 'Rebecca'), book(2, 'Dracula')] }),
        }],
        shelf: turn(1, { results: [book(1, 'Rebecca'), book(2, 'Dracula')] }),
      }),
    )

    const answer = screen.getByRole('region', { name: 'Answer' })
    expect(answer).toHaveTextContent('gothic horror please')
    expect(answer).toHaveTextContent('Heard “shirley jackson” as Shirley Jackson')
    expect(answer).toHaveTextContent('Two gothic ones.')
    expect(answer).toHaveTextContent('Older, or newer?')
    const books = within(screen.getByRole('list', { name: 'Books' })).getAllByRole('button')
    expect(books.map((b) => b.getAttribute('aria-label'))).toEqual(['1. Rebecca', '2. Dracula'])

    await userEvent.click(books[1])
    expect(screen.getByRole('dialog')).toHaveTextContent('Dracula')
  })

  it('says what it is doing, and the microphone stops listening when tapped again', async () => {
    render(<LivePage />)
    act(() => useSession.setState({ status: 'listening', listening: true }))
    expect(screen.getByText('Listening', { selector: '.live-status' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Stop listening' }))
    expect(conversation.listen).toHaveBeenCalled()

    act(() => useSession.setState({ status: 'ready', listening: false, playing: true }))
    expect(screen.getByText('Speaking', { selector: '.live-status' })).toBeInTheDocument()
    expect(screen.getByText('Tap to interrupt')).toBeInTheDocument()
  })

  it('switches hands-free and the avatar, and says when there is no voice', async () => {
    render(<LivePage />)
    await userEvent.click(screen.getByRole('button', { name: 'Hands-free' }))
    expect(conversation.toggleHandsFree).toHaveBeenCalled()

    const avatar = screen.getByRole('button', { name: 'Avatar on' })
    await userEvent.click(avatar)
    expect(screen.getByRole('button', { name: 'Avatar off' })).toHaveAttribute('aria-pressed', 'false')

    act(() => useSession.setState({ speakOn: false }))
    expect(screen.getByText(/No voice/)).toBeInTheDocument()
  })
})
