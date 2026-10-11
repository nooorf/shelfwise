// Avatar or orb (design doc §21.4 fallbacks). The orb is the floor: no WebGL, a request for
// reduced motion, no model file, a failed load or a slow device all fall back to it.

export type OrbReason = 'off' | 'reduced-motion' | 'no-webgl' | 'missing' | 'load' | 'slow'

export interface Conditions {
  wanted: boolean // the reader's setting
  reducedMotion: boolean
  webgl: boolean
  model: string | null // URL of a model that exists, null if none
  failed: 'load' | 'slow' | null
}

/** Why the orb shows instead of the avatar, or null to show the avatar. */
export function orbReason(c: Conditions): OrbReason | null {
  if (!c.wanted) return 'off'
  if (c.reducedMotion) return 'reduced-motion'
  if (!c.webgl) return 'no-webgl'
  if (!c.model) return 'missing'
  return c.failed
}

export const ORB_NOTES: Record<OrbReason, string> = {
  off: 'Avatar off',
  'reduced-motion': 'Avatar off: reduced motion is on',
  'no-webgl': 'Avatar unavailable: no WebGL',
  missing: 'No avatar model (make download-avatar)',
  load: 'The avatar didn’t load',
  slow: 'Avatar off: too slow on this device',
}

/** Your own model first, then the downloaded sample. */
export const MODEL_URLS = ['/avatar/shelfwise.vrm', '/avatar/sample.vrm']

/** The first model URL that serves a binary file (a dev server answers missing files with
 * its HTML page, so the type is checked, not just the status). */
export async function findModel(fetcher: typeof fetch = fetch): Promise<string | null> {
  for (const url of MODEL_URLS) {
    try {
      const response = await fetcher(url, { method: 'HEAD' })
      const type = response.headers.get('content-type') ?? ''
      if (response.ok && !type.startsWith('text/')) return url
    } catch {
      // try the next one
    }
  }
  return null
}

export function hasWebGL(): boolean {
  try {
    const canvas = document.createElement('canvas')
    return Boolean(canvas.getContext('webgl2') ?? canvas.getContext('webgl'))
  } catch {
    return false
  }
}

const AVATAR_KEY = 'shelfwise.avatar'

/** The reader's avatar switch, remembered per browser; on unless switched off. */
export function readAvatarSetting(): boolean {
  try {
    return globalThis.localStorage?.getItem(AVATAR_KEY) !== 'off'
  } catch {
    return true
  }
}

export function writeAvatarSetting(on: boolean): boolean {
  try {
    globalThis.localStorage?.setItem(AVATAR_KEY, on ? 'on' : 'off')
  } catch {
    // not remembered; the switch still holds for this page
  }
  return on
}
