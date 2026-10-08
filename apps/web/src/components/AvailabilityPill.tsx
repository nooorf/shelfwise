// Never colour alone (design doc §22.1): every state has an icon and words.
import { BookCheck, BookX, Clock, Library, Ban } from 'lucide-react'
import type { ComponentType } from 'react'

import type { Availability } from '../api/types'
import { availabilityText } from './availability'

const STYLES: Record<string, { icon: ComponentType<{ className?: string }>; tone: string }> = {
  available: { icon: BookCheck, tone: 'bg-ok-soft text-ok' },
  due_soon: { icon: Clock, tone: 'bg-soon-soft text-soon' },
  borrowed: { icon: BookX, tone: 'bg-out-soft text-out' },
  in_library_only: { icon: Library, tone: 'bg-quiet-soft text-quiet' },
  unavailable: { icon: Ban, tone: 'bg-quiet-soft text-quiet' },
}

export function AvailabilityPill({ availability }: { availability: Availability }) {
  const { icon: Icon, tone } = STYLES[availability.state] ?? STYLES.unavailable
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs ${tone}`}>
      <Icon className="size-3.5 shrink-0" aria-hidden="true" />
      {availabilityText(availability)}
    </span>
  )
}
