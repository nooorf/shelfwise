// The chat's input: the landing page's dark box, grown to a few lines as you type. Enter sends,
// Shift+Enter starts a new line; while an answer is coming the button stops it instead.
import { ArrowUp, Square } from 'lucide-react'
import { useLayoutEffect, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'

const MAX_HEIGHT = 200

interface Props {
  onAsk: (text: string) => void
  onCancel: () => void
  busy: boolean
  autoFocus?: boolean
}

export function Composer({ onAsk, onCancel, busy, autoFocus = false }: Props) {
  const [value, setValue] = useState('')
  const box = useRef<HTMLTextAreaElement>(null)

  useLayoutEffect(() => {
    const el = box.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT)}px`
  }, [value])

  function send(e?: FormEvent) {
    e?.preventDefault()
    const text = value.trim()
    if (!text) return
    onAsk(text)
    setValue('')
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) send(e)
  }

  return (
    <form className="composer" onSubmit={send} role="search">
      <label htmlFor="ask" className="sr-only">
        Ask for a book
      </label>
      <textarea
        id="ask"
        ref={box}
        className="composer-input"
        rows={1}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={onKeyDown}
        placeholder="Ask for a book, or tell me what to change"
        autoComplete="off"
        maxLength={500}
        // The page is about this box: on an empty chat it takes the keyboard at once.
        // oxlint-disable-next-line jsx-a11y/no-autofocus
        autoFocus={autoFocus}
      />
      {busy ? (
        <button type="button" className="composer-go is-stop" onClick={onCancel} aria-label="Stop">
          <Square className="size-3.5" fill="currentColor" aria-hidden="true" />
        </button>
      ) : (
        <button type="submit" className="composer-go" aria-label="Ask">
          <ArrowUp className="size-4" strokeWidth={2.25} aria-hidden="true" />
        </button>
      )}
    </form>
  )
}
