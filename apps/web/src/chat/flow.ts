// Where each book stands in the chat's Cover Flow (CoverFlow.tsx).
import type { CSSProperties } from 'react'

export const VISIBLE = 4 // books shown on each side of the one in focus

/** Where a book stands, `offset` places from the one in focus (negative: to its left). The
 * first neighbour stands well clear of the focus; the rest close up behind it. */
export function placement(offset: number): CSSProperties {
  const away = Math.abs(offset)
  if (away === 0) return { transform: 'translate3d(-50%, 0, 60px)', zIndex: 20 }
  const side = Math.sign(offset)
  const x = -50 + side * (78 + (away - 1) * 34) // percent of a cover's width
  return {
    transform: `translate3d(${x}%, 0, ${-away * 110}px) rotateY(${-side * 50}deg)`,
    zIndex: 20 - away,
    opacity: away > VISIBLE ? 0 : 1 - (away - 1) * 0.16,
    pointerEvents: away > VISIBLE ? 'none' : undefined,
  }
}
