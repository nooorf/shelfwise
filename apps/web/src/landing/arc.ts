// Where each featured book sits on the landing page's arc, as if seen from the doorway of a
// round reading room: the far shelf (a dark panel of small covers) straight ahead, and the
// walls curving round to either side, each book a little nearer, larger and more turned
// toward you than the last, until the nearest are cropped by the edge of the screen.
// Pure layout numbers, so they can be tested without a browser.

export const COVER = { w: 120, h: 180 } // a cover at scale 1, in CSS pixels

export interface Placement {
  x: number // centre, pixels from the middle of the arc
  scale: number
  turn: number // degrees about the vertical axis; positive faces the left wall's books right
  side: -1 | 0 | 1 // left wall, far shelf, right wall
  ring: number // 0 for the far shelf, then 1, 2, ... outward
}

export interface Arc {
  shelf: { width: number; height: number; scale: number; count: number }
  places: Placement[] // shelf books left to right, then the walls; see order()
  unit: number // the scale that maps the 1440-pixel design onto this screen
}

const SHELF_GAP = 6
const SHELF_PAD = 8
const GROWTH = 1.46 // each book on a wall, relative to the one before
const FIRST = { scale: 0.6, turn: 16 }
const TURN_STEP = 9
const MAX_TURN = 56

/** The arc for a screen `width` pixels wide holding up to `available` books. Walls stop at
 * the first book entirely off screen; the far shelf holds five books, three when narrow. */
export function layout(width: number, height: number, available: number): Arc {
  const narrow = width < 768
  const unit = narrow ? width / 400 : Math.min(width / 1440, height / 820)
  const shelfCount = Math.min(narrow ? 3 : 5, available)
  const shelfScale = 0.5 * unit
  const coverW = COVER.w * shelfScale
  const shelf = {
    count: shelfCount,
    scale: shelfScale,
    width: shelfCount * coverW + (shelfCount - 1) * SHELF_GAP * unit + 2 * SHELF_PAD * unit,
    height: COVER.h * shelfScale + 2 * SHELF_PAD * unit,
  }

  const places: Placement[] = []
  const left = shelf.width / 2 - SHELF_PAD * unit - coverW / 2
  for (let i = 0; i < shelfCount; i++) {
    places.push({ x: -left + i * (coverW + SHELF_GAP * unit), scale: shelfScale, turn: 0, side: 0, ring: 0 })
  }

  // The walls, outward in pairs, while books remain and the last one is still on screen.
  let edge = shelf.width / 2 // inner edge of the next book, from the middle
  let scale = FIRST.scale * unit
  let turn = FIRST.turn
  for (let ring = 1; places.length + 2 <= available; ring++) {
    const seen = COVER.w * scale * Math.cos((turn * Math.PI) / 180) // width after turning
    const gap = -ring * 1.5 * unit // a slight overlap, nearer over farther: one wall, not a row of cards
    const x = edge + gap + seen / 2
    if (x - seen / 2 > width / 2) break
    places.push({ x: -x, scale, turn, side: -1, ring }, { x, scale, turn: -turn, side: 1, ring })
    edge = x + seen / 2
    scale *= GROWTH
    turn = Math.min(turn + TURN_STEP, MAX_TURN)
  }
  return { shelf, places, unit }
}

/** Left-to-right reading order of the placements (for the tab order and screen readers). */
export function order(places: Placement[]): number[] {
  return places.map((_, i) => i).sort((a, b) => places[a].x - places[b].x)
}
