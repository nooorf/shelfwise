// Availability in words: the pill's text, testable without rendering.
import type { Availability } from '../api/types'

export function dueLabel(isoDate: string, today: Date = new Date()): string {
  const due = new Date(`${isoDate}T00:00:00`)
  const days = Math.round((due.getTime() - new Date(today.toDateString()).getTime()) / 86_400_000)
  if (days <= 0) return 'Due back today'
  if (days < 7) return `Due back ${due.toLocaleDateString('en-GB', { weekday: 'short' })}`
  return `Due back ${due.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })}`
}

export function availabilityText(a: Availability, today?: Date): string {
  const where = a.location
    ? [a.location.floor && `Floor ${a.location.floor}`, a.location.call_number]
        .filter(Boolean)
        .join(' · ')
    : ''
  switch (a.state) {
    case 'available':
      return ['Available', where].filter(Boolean).join(' · ')
    case 'in_library_only':
      return ['In library only', where].filter(Boolean).join(' · ')
    case 'due_soon':
    case 'borrowed':
      return a.next_due ? dueLabel(a.next_due, today) : 'Borrowed'
    default:
      return 'Not available'
  }
}
