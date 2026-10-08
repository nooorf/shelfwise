// What the search is holding right now (design doc §22.1). Solid chips are must-haves (hard
// filters), dashed ones preferences. Each has a remove button: the search runs again without it.
import { X } from 'lucide-react'

import type { Chip } from '../api/types'

export function ChipBar({ chips, onRemove }: { chips: Chip[]; onRemove: (chip: Chip) => void }) {
  if (chips.length === 0) return null
  return (
    <ul aria-label="Active filters" className="flex flex-wrap items-center gap-1.5">
      <li className="mr-1 text-xs font-semibold tracking-wide text-muted uppercase">Active</li>
      {chips.map((chip) => (
        <li
          key={`${chip.field}:${chip.label}`}
          title={chip.strength === 'hard' ? 'Must' : 'Preferred'}
          className={`inline-flex items-center gap-1 rounded-full border py-0.5 pr-1 pl-2.5 text-sm ${
            chip.strength === 'hard'
              ? 'border-accent bg-accent-soft text-accent'
              : 'border-dashed border-muted text-ink'
          }`}
        >
          {chip.label}
          <span className="sr-only">{chip.strength === 'hard' ? ' (must)' : ' (preferred)'}</span>
          <button
            type="button"
            onClick={() => onRemove(chip)}
            aria-label={`Remove ${chip.label}`}
            className="rounded-full p-0.5 opacity-70 hover:opacity-100 focus-visible:opacity-100 focus-visible:outline-2 focus-visible:outline-current"
          >
            <X className="size-3.5" aria-hidden="true" />
          </button>
        </li>
      ))}
    </ul>
  )
}
