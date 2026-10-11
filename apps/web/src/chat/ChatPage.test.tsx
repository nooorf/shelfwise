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

  it('puts the newest answer on the stage, and an older one back when its covers are clicked', async () => {
    render(<ChatPage />)
    expect(screen.queryByRole('region', { name: /Books for/ })).toBeNull()
    exchanges(
      { said: 'dark thrillers', turn: 1, response: turn(1, { results: [book(1, 'Sharp Objects'), book(2, 'Gone Girl')] }), reply },
      { said: 'older ones', turn: 2, response: turn(2, { results: [book(3, 'Rebecca')] }) },
    )

    expect(screen.getByText('Two quiet, dark ones.')).toBeInTheDocument()
    expect(screen.getByText('Shorter, or older?')).toBeInTheDocument()
    expect(screen.getAllByText('How it searched')).toHaveLength(2)
    expect(screen.getByRole('region', { name: 'Books for “older ones”' })).toHaveTextContent('Rebecca')

    const [first] = screen.getAllByRole('list', { name: 'Books' })
    await userEvent.click(within(first).getByRole('button', { name: 'Show Gone Girl' }))
    const stage = screen.getByRole('region', { name: 'Books for “dark thrillers”' })
    expect(within(stage).getByRole('heading', { level: 2 })).toHaveTextContent('Gone Girl')
    expect(within(stage).getByText('2 of 2')).toBeInTheDocument()
    expect(within(first).getByRole('button', { name: 'Show Gone Girl' })).toHaveAttribute('aria-pressed', 'true')

    exchanges(
      { said: 'dark thrillers', turn: 1, response: turn(1, { results: [book(1, 'Sharp Objects'), book(2, 'Gone Girl')] }), reply },
      { said: 'older ones', turn: 2, response: turn(2, { results: [book(3, 'Rebecca')] }) },
      { said: 'poetry', turn: 3, response: turn(3, { results: [book(4, 'Ariel')] }) },
    )
    expect(screen.getByRole('region', { name: 'Books for “poetry”' })).toBeInTheDocument() // the newest takes it back
  })

  it('steps through the books with the arrows, the keys and the dots, each with its note', async () => {
    render(<ChatPage />)
    exchanges({
      said: 'dark thrillers', turn: 1, reply,
      response: turn(1, { results: [book(1, 'Sharp Objects'), book(2, 'Gone Girl'), book(3, 'Rebecca')] }),
    })
    const stage = screen.getByRole('region', { name: 'Books for “dark thrillers”' })
    const title = () => within(stage).getByRole('heading', { level: 2 }).textContent

    expect(title()).toBe('Sharp Objects')
    expect(within(stage).getByText('A slow unravelling.')).toBeInTheDocument()
    expect(within(stage).getByRole('button', { name: 'Previous book' })).toBeDisabled()
    await userEvent.click(within(stage).getByRole('button', { name: 'Next book' }))
    expect(title()).toBe('Gone Girl')
    await userEvent.keyboard('{ArrowRight}')
    expect(title()).toBe('Rebecca')
    expect(within(stage).getByRole('button', { name: 'Next book' })).toBeDisabled()
    await userEvent.click(within(stage).getByRole('button', { name: 'Show Sharp Objects' }))
    expect(title()).toBe('Sharp Objects')
    await userEvent.click(within(stage).getByRole('button', { name: 'Book 2: Gone Girl' }))
    expect(title()).toBe('Gone Girl')
    await userEvent.click(within(stage).getByRole('button', { name: 'More like Gone Girl' }))
    expect(conversation.feedback).toHaveBeenCalledWith(expect.objectContaining({ title: 'Gone Girl' }), true)
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

  it('opens the book in focus in the drawer', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 500 })))
    render(<ChatPage />)
    exchanges({ said: 'dark thrillers', turn: 1, response: turn(1, { results: [book(1, 'Sharp Objects')] }), reply })

    await userEvent.click(screen.getByRole('button', { name: 'Open Sharp Objects' }))
    expect(screen.getByRole('dialog')).toHaveTextContent('Sharp Objects')
    vi.unstubAllGlobals()
  })
})
