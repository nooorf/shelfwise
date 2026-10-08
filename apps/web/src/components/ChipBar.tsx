// What the search is holding right now (design doc §22.1). Solid chips are must-haves (hard
// filters), dashed ones preferences. Removing one by click comes with the chip endpoint.
import type { Chip } from '../api/types'

export function ChipBar({ chips }: { chips: Chip[] }) {
  if (chips.length === 0) return null
  return (
    <ul aria-label="Active filters" className="flex flex-wrap items-center gap-1.5">
      <li className="mr-1 text-xs font-semibold tracking-wide text-muted uppercase">Active</li>
      {chips.map((chip) => (
        <li
          key={`${chip.field}:${chip.label}`}
          title={chip.strength === 'hard' ? 'Must' : 'Preferred'}
          className={`rounded-full border px-2.5 py-0.5 text-sm ${
            chip.strength === 'hard'
              ? 'border-accent bg-accent-soft text-accent'
              : 'border-dashed border-muted text-ink'
          }`}
        >
          {chip.label}
          <span className="sr-only">{chip.strength === 'hard' ? ' (must)' : ' (preferred)'}</span>
        </li>
      ))}
    </ul>
  )
}
