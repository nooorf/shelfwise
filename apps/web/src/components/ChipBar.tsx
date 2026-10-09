// What the search is holding right now (design doc §22.1). Solid chips are must-haves (hard
// filters), dashed ones preferences. Each has a remove button: the search runs again without it.
// A switchable chip's label is a toggle between must and preferred; the rest (e.g. "available
// now", which only filters) stay as they are.
import { X } from 'lucide-react'

import type { Chip } from '../api/types'

interface ChipBarProps {
  chips: Chip[]
  onRemove: (chip: Chip) => void
  onSwitch: (chip: Chip) => void
}

export function ChipBar({ chips, onRemove, onSwitch }: ChipBarProps) {
  if (chips.length === 0) return null
  return (
    <ul aria-label="Active filters" className="flex flex-wrap items-center gap-1.5">
      <li className="mr-1 text-xs font-semibold tracking-wide text-muted uppercase">Active</li>
      {chips.map((chip) => (
        <li
          key={`${chip.field}:${chip.label}`}
          className={`inline-flex items-center gap-1 rounded-full border py-0.5 pr-1 pl-2.5 text-sm ${
            chip.strength === 'hard'
              ? 'border-accent bg-accent-soft text-accent'
              : 'border-dashed border-muted text-ink'
          }`}
        >
          {chip.switchable ? (
            <button
              type="button"
              onClick={() => onSwitch(chip)}
              aria-pressed={chip.strength === 'hard'}
              aria-label={`Must have ${chip.label}`}
              title={chip.strength === 'hard' ? 'Must: tap to make it a preference' : 'Preferred: tap to make it a must'}
              className="rounded-full hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-current"
            >
              {chip.label}
            </button>
          ) : (
            <span title={chip.strength === 'hard' ? 'Must' : 'Preferred'}>{chip.label}</span>
          )}
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
