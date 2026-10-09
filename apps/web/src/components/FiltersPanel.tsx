// Advanced filters (design doc §22.3): form fields become must chips, no LLM call. Empty
// fields are left alone; to undo one, remove its chip.
import { useState } from 'react'
import type { FormEvent } from 'react'

import type { Filters } from '../api/types'

const number = (text: string): number | null => (text.trim() ? Number(text) : null)

export function FiltersPanel({ onApply }: { onApply: (filters: Filters) => void }) {
  const [pages, setPages] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [available, setAvailable] = useState(false)

  const filters: Filters = {
    pages_max: number(pages),
    year_from: number(from),
    year_to: number(to),
    available_now: available ? true : null,
  }
  const empty = Object.values(filters).every((v) => v == null)

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!empty) onApply(filters)
  }

  const field = 'w-24 rounded-md border border-line bg-card px-2 py-1 tabular-nums focus:border-accent focus:outline-none'
  return (
    <form onSubmit={submit} aria-label="Filters" className="flex flex-wrap items-end gap-x-4 gap-y-2 text-sm">
      <label className="flex flex-col gap-1">
        At most (pages)
        <input type="number" min={10} max={3000} value={pages} onChange={(e) => setPages(e.target.value)} className={field} />
      </label>
      <label className="flex flex-col gap-1">
        Published from
        <input type="number" min={0} max={2100} value={from} onChange={(e) => setFrom(e.target.value)} className={field} />
      </label>
      <label className="flex flex-col gap-1">
        to
        <input type="number" min={0} max={2100} value={to} onChange={(e) => setTo(e.target.value)} className={field} />
      </label>
      <label className="flex items-center gap-2 py-1">
        <input type="checkbox" checked={available} onChange={(e) => setAvailable(e.target.checked)} className="size-4 accent-accent" />
        Available now
      </label>
      <button
        type="submit"
        disabled={empty}
        className="rounded-full bg-accent px-4 py-1.5 text-card disabled:opacity-40"
      >
        Apply
      </button>
    </form>
  )
}
