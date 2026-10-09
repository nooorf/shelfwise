// The ways in besides asking (design doc §22.1, §22.3). None of them calls the LLM: each builds
// the request straight from what was tapped. Explore and Filters open a panel below the bar;
// Escape or a choice closes it and puts focus back on its tab.
import { Compass, Shuffle, SlidersHorizontal } from 'lucide-react'
import { useRef, useState } from 'react'
import type { ReactNode } from 'react'

import type { Filters } from '../api/types'
import { ExplorePanel } from './ExplorePanel'
import { FiltersPanel } from './FiltersPanel'

type Panel = 'explore' | 'filters'

interface ModeBarProps {
  onSurprise: () => void
  onExplore: (genre: string) => void
  onFilters: (filters: Filters) => void
}

const pill =
  'inline-flex items-center gap-1.5 rounded-full border px-3 py-1 hover:border-accent hover:text-accent focus-visible:outline-2 focus-visible:outline-accent'

export function ModeBar({ onSurprise, onExplore, onFilters }: ModeBarProps) {
  const [open, setOpen] = useState<Panel | null>(null)
  const tabs = useRef<Partial<Record<Panel, HTMLButtonElement | null>>>({})

  const close = () => {
    if (open) tabs.current[open]?.focus()
    setOpen(null)
  }

  const tab = (panel: Panel, icon: ReactNode, name: string) => (
    <button
      ref={(el) => {
        tabs.current[panel] = el
      }}
      type="button"
      aria-expanded={open === panel}
      aria-controls={`mode-${panel}`}
      onClick={() => setOpen(open === panel ? null : panel)}
      className={`${pill} ${open === panel ? 'border-accent bg-accent-soft text-accent' : 'border-line text-ink'}`}
    >
      {icon} {name}
    </button>
  )

  return (
    <div className="flex flex-col gap-2">
      <nav aria-label="Ways to search" className="flex flex-wrap items-center gap-1.5 text-sm">
        {tab('explore', <Compass className="size-3.5" aria-hidden="true" />, 'Explore')}
        <button type="button" onClick={onSurprise} className={`${pill} border-line text-ink`}>
          <Shuffle className="size-3.5" aria-hidden="true" /> Surprise me
        </button>
        {tab('filters', <SlidersHorizontal className="size-3.5" aria-hidden="true" />, 'Filters')}
      </nav>
      {open && (
        <div
          id={`mode-${open}`}
          onKeyDown={(event) => event.key === 'Escape' && close()}
          className="rounded-lg border border-line bg-card p-3"
        >
          {open === 'explore' ? (
            <ExplorePanel
              onExplore={(genre) => {
                close()
                onExplore(genre)
              }}
            />
          ) : (
            <FiltersPanel
              onApply={(filters) => {
                close()
                onFilters(filters)
              }}
            />
          )}
        </div>
      )}
    </div>
  )
}
