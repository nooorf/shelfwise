// Where the landing page's character looks. A book someone points at wins; otherwise a moving
// cursor; otherwise it browses the arc, resting on one book for GLANCE_S seconds before
// hopping to another, until the cursor moves again (and for FOLLOW_S seconds after it stops).

export const FOLLOW_S = 2
export const GLANCE_S = 1.7

export interface Point {
  x: number
  y: number
}

export interface Vec3 extends Point {
  z: number
}

export type GazeMode = 'book' | 'cursor' | 'browse'

/** The book browsed at `now`: a fixed stride through the list, so the eyes hop across the
 * arc instead of sweeping along it. */
export function browsed(now: number, count: number): number {
  const step = Math.floor(now / GLANCE_S)
  let stride = count > 4 ? Math.max(2, Math.round(count * 0.38)) : 1
  while (gcd(stride, count) !== 1) stride += 1 // so every book gets its turn
  return (step * stride) % count
}

function gcd(a: number, b: number): number {
  return b === 0 ? a : gcd(b, a % b)
}

/** Seconds are any monotonic clock; points are viewport pixels. Null when there is nothing
 * to look at (no cursor yet and no books): the head stays as it is. */
export function gazeTarget(
  now: number,
  cursor: (Point & { at: number }) | null,
  books: Point[],
  pointed: Point | null,
): (Point & { mode: GazeMode }) | null {
  if (pointed) return { ...pointed, mode: 'book' }
  if (cursor && now - cursor.at < FOLLOW_S) return { x: cursor.x, y: cursor.y, mode: 'cursor' }
  if (books.length === 0) return cursor ? { x: cursor.x, y: cursor.y, mode: 'cursor' } : null
  return { ...books[browsed(now, books.length)], mode: 'browse' }
}

export const LIMITS = { yaw: 0.6, up: 0.35, down: 0.5 } // radians, head and neck together

/** Turn (yaw, + toward +x) and tilt (pitch, + up) that point the head at `target`, clamped
 * to what a neck can do. The model faces +z, toward the camera. */
export function aim(head: Vec3, target: Vec3): { yaw: number; pitch: number } {
  const dx = target.x - head.x
  const dy = target.y - head.y
  const dz = Math.max(target.z - head.z, 0.05) // never look behind
  const yaw = Math.atan2(dx, dz)
  const pitch = Math.atan2(dy, Math.hypot(dx, dz))
  return {
    yaw: Math.max(-LIMITS.yaw, Math.min(LIMITS.yaw, yaw)),
    pitch: Math.max(-LIMITS.down, Math.min(LIMITS.up, pitch)),
  }
}

/** Frame-rate independent easing toward a target with time constant `tau` seconds. */
export function approach(value: number, target: number, dt: number, tau: number): number {
  return value + (target - value) * (1 - Math.exp(-dt / tau))
}

/** The peek: 0 hidden behind the shelf, 1 fully up, overshooting a little on the way (an
 * ease-out-back), over `duration` seconds from `start`. */
export function rise(t: number, start: number, duration: number): number {
  const p = Math.min(Math.max((t - start) / duration, 0), 1)
  const c = 1.6
  return 1 + (c + 1) * (p - 1) ** 3 + c * (p - 1) ** 2
}
