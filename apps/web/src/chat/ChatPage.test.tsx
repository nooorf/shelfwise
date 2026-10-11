import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Reply } from '../api/types'
import { useSession } from '../session/store'
import type { Exchange } from '../session/store'
import { book, turn } from '../test/fixtures'
import { ChatPage } from './ChatPage'

const conversation = {
  ask: vi.fn(), undo: vi.fn(), removeChip: vi.fn(), switchChip: vi.fn(), feedback: vi.fn(),
  surprise: vi.fn(), explore: vi.fn(), filter: vi.fn(), cancel: vi.fn(), toggleSpeech: vi.fn(),
  listen: vi.fn(), toggleHandsFree: vi.fn(), newVisitor: vi.fn(async () => {}),
}
const options: unknown[] = []

vi.mock('../session/useConversation', () => ({
  useConversation: (o: unknown) => {
    options.push(o)
    return conversation
  },
}))

const reply: Reply = {
  intro: 'Two quiet, dark ones.',
  items: [{ work_id: 1, why: 'A slow unravelling.', source: 'llm' }],
  follow_up: 'Shorter, or older?',
  source: 'llm',
  problems: [],
  attempts: 1,
  ms: 10,
}

function exchanges(...list: Partial<Exchange>[]): void {
  act(() => useSession.setState({ exchanges: list.map((e, i) => ({ key: i + 1, said: '', pending: false, ...e })) }))
}

beforeEach(() => {
  vi.clearAllMocks()
  options.length = 0
  useSession.setState({ exchanges: [], status: 'ready', error: null })
})

afterEach(() => window.history.pushState(null, '', '/'))

describe('chat page', () => {
  it('asks the question a reader typed, from the box or with Enter, and never speaks', async () => {
    render(<ChatPage />)
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('What would you like to read?')
    expect(options[0]).toEqual({ speech: false })

    await userEvent.type(screen.getByRole('textbox', { name: 'Ask for a book' }), 'cozy mysteries{Enter}')
    expect(conversation.ask).toHaveBeenCalledWith('cozy mysteries')

    await userEvent.click(screen.getByRole('button', { name: 'a short mystery I can borrow today' }))
    expect(conversation.ask).toHaveBeenLastCalledWith('a short mystery I can borrow today')
  })

  it('asks a question handed over from the landing page once, and drops it from the address', () => {
    window.history.pushState(null, '', '/chat?q=books%20about%20grief')
    render(<ChatPage />)
    expect(conversation.ask).toHaveBeenCalledWith('books about grief')
    expect(window.location.search).toBe('')
  })

  it('shows each answer with its own books and notes, and how it searched', () => {
    render(<ChatPage />)
    exchanges(
      { said: 'dark thrillers', turn: 1, response: turn(1, { results: [book(1, 'Sharp Objects'), book(2, 'Gone Girl')] }), reply },
      { said: 'older ones', turn: 2, response: turn(2, { results: [book(3, 'Rebecca')] }) },
    )

    expect(screen.getByText('dark thrillers')).toBeInTheDocument()
    expect(screen.getByText('Two quiet, dark ones.')).toBeInTheDocument()
    expect(screen.getByText('A slow unravelling.')).toBeInTheDocument()
    expect(screen.getByText('Shorter, or older?')).toBeInTheDocument()

    const strips = screen.getAllByRole('list', { name: 'Books' })
    expect(strips).toHaveLength(2)
    expect(within(strips[0]).getAllByRole('article').map((a) => a.getAttribute('aria-label'))).toEqual([
      '1. Sharp Objects',
      '2. Gone Girl',
    ])
    expect(within(strips[1]).getByRole('article', { name: '1. Rebecca' })).toBeInTheDocument()
    expect(screen.getAllByText('How it searched')).toHaveLength(2)
  })

  it('says it is looking, and the button stops the answer while one is coming', async () => {
    render(<ChatPage />)
    exchanges({ said: 'vampire novels', pending: true })

    expect(screen.getByText(/Looking through the shelves/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Stop' }))
    expect(conversation.cancel).toHaveBeenCalled()
  })

  it('keeps what the search holds by the box, and offers did-you-mean only on the latest answer', async () => {
    render(<ChatPage />)
    const guesses = [{ title: 'The Secret History', ask: 'the secret history' }]
    exchanges(
      { said: 'secrit history', turn: 1, response: turn(1, { results: [], guesses }) },
      {
        said: 'under 300 pages', turn: 2,
        response: turn(2, {
          can_undo: true,
          chips: [{ field: 'pages', label: 'under 300 pages', op: 'lt', value: 300, strength: 'hard', polarity: 'include', turn: 2, switchable: false }],
        }),
      },
    )

    expect(screen.queryByText('Did you mean…')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Remove under 300 pages' }))
    expect(conversation.removeChip).toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: /Back to previous search/ }))
    expect(conversation.undo).toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'New chat' }))
    expect(conversation.newVisitor).toHaveBeenCalled()
  })

  it('opens a book from an answer in the drawer', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 500 })))
    render(<ChatPage />)
    exchanges({ said: 'dark thrillers', turn: 1, response: turn(1, { results: [book(1, 'Sharp Objects')] }), reply })

    await userEvent.click(screen.getByRole('button', { name: 'Sharp Objects' }))
    expect(screen.getByRole('dialog')).toHaveTextContent('Sharp Objects')
    vi.unstubAllGlobals()
  })
})
