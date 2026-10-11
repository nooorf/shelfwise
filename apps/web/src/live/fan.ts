// Where each cover sits on the live page's fan (BookFan.tsx).

/** A cover's place on the fan, `index` of `count`: spread from the middle, dropping and
 * turning a little toward the ends. `x` is in percent of a cover's width, so a long answer
 * overlaps its covers a little more. */
export function fanPlace(index: number, count: number): { x: number; y: number; turn: number } {
  const t = index - (count - 1) / 2
  return { x: t * (count > 6 ? 70 : 92), y: t * t * 7, turn: t * 5 }
}
