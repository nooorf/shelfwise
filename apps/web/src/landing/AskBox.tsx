// The landing page's main action: ask for a book in your own words, and the question opens
// the chat with it already asked (/chat?q=...). While the box is empty and not in use, it
// types out real example requests; with reduced motion it shows the first one, still.
import { ArrowUp } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'

import { navigate } from '../router'
import { EXAMPLES } from './examples'

const TYPE_MS = 42
const ERASE_MS = 18
const HOLD_MS = 1900

function useTypedExample(paused: boolean): string {
  const [text, setText] = useState(EXAMPLES[0])
  useEffect(() => {
    if (paused || globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return
    let example = 0
    let shown = EXAMPLES[0].length
    let phase: 'hold' | 'erase' | 'type' = 'hold'
    let timer = setTimeout(tick, HOLD_MS)
    function tick() {
      if (phase === 'hold') phase = 'erase'
      if (phase === 'erase') {
        shown -= 1
        if (shown === 0) {
          example = (example + 1) % EXAMPLES.length
          phase = 'type'
        }
      } else {
        shown += 1
        if (shown === EXAMPLES[example].length) phase = 'hold'
      }
      setText(EXAMPLES[example].slice(0, shown))
      timer = setTimeout(tick, phase === 'hold' ? HOLD_MS : phase === 'erase' ? ERASE_MS : TYPE_MS)
    }
    return () => clearTimeout(timer)
  }, [paused])
  return text
}

export function AskBox() {
  const [value, setValue] = useState('')
  const [focused, setFocused] = useState(false)
  const example = useTypedExample(focused || value.length > 0)

  function submit(e: FormEvent) {
    e.preventDefault()
    const question = value.trim()
    if (!question) {
      document.getElementById('landing-ask')?.focus()
      return
    }
    navigate(`/chat?q=${encodeURIComponent(question)}`)
  }

  return (
    <form className="ask" onSubmit={submit} role="search">
      <label htmlFor="landing-ask" className="sr-only">
        Ask for a book
      </label>
      <input
        id="landing-ask"
        className="ask-input"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        placeholder={focused ? 'Ask for a book' : ''}
        autoComplete="off"
        maxLength={500}
      />
      {!focused && value.length === 0 && (
        <span className="ask-example" aria-hidden="true">
          {example}
        </span>
      )}
      <button type="submit" className="ask-go" aria-label="Ask">
        <ArrowUp className="size-4" strokeWidth={2.25} aria-hidden="true" />
      </button>
    </form>
  )
}
