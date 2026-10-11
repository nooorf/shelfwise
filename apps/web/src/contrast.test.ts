// WCAG AA for every text/background pair the components use, in every theme (design doc
// §22.4): 4.5:1 for text. Reads the tokens from index.css, so a colour edit can't regress it.
import { describe, expect, it } from 'vitest'

import css from './index.css?raw'

const PAIRS: [string, string][] = [
  ['ink', 'paper'], ['ink', 'card'], ['muted', 'paper'], ['muted', 'card'], ['muted', 'accent-soft'],
  ['accent', 'paper'], ['accent', 'card'], ['accent', 'accent-soft'], ['ink', 'accent-soft'],
  ['card', 'accent'], ['ok', 'ok-soft'], ['soon', 'soon-soft'], ['out', 'out-soft'],
  ['out', 'paper'], ['quiet', 'quiet-soft'],
  ...Array.from({ length: 12 }, (_, i): [string, string] => [`seq-ink-${i}`, `seq-${i}`]),
]

function tokens(block: string): Record<string, string> {
  return Object.fromEntries([...block.matchAll(/--color-([\w-]+): (#[0-9a-f]{6})/g)].map((m) => [m[1], m[2]]))
}

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

function ratio(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

// The reading room's own colour roles: butter and coral fields and buttons carry ink, and the
// dark pills (nav, ask box) carry their own light ink.
const ROOM_PAIRS: [string, string][] = [
  ['ink', 'butter'], ['ink', 'coral'], ['butter', 'ink'], ['night-ink', 'night'], ['night-muted', 'night'],
]

const [systemCss, roomCss] = css.split('\n.reading-room {')
const [lightCss, darkCss] = systemCss.split('@media (prefers-color-scheme: dark)')
const light = tokens(lightCss)
const room = { ...light, ...tokens(roomCss.split('}')[0]) }
const themes = { light, dark: { ...light, ...tokens(darkCss) }, 'reading room': room }

describe('colour contrast', () => {
  it('checks the formula against known values', () => {
    expect(ratio('#000000', '#ffffff')).toBeCloseTo(21)
    expect(ratio('#777777', '#ffffff')).toBeCloseTo(4.48, 2)
  })

  for (const [theme, colors] of Object.entries(themes)) {
    it(`meets AA for text in the ${theme} theme`, () => {
      const failing = PAIRS.filter(([fg, bg]) => ratio(colors[fg], colors[bg]) < 4.5).map(
        ([fg, bg]) => `${fg} on ${bg}: ${ratio(colors[fg], colors[bg]).toFixed(2)}`,
      )
      expect(failing).toEqual([])
    })
  }

  it('meets AA for the reading room\'s colour roles', () => {
    const failing = ROOM_PAIRS.filter(([fg, bg]) => ratio(room[fg], room[bg]) < 4.5).map(
      ([fg, bg]) => `${fg} on ${bg}: ${ratio(room[fg], room[bg]).toFixed(2)}`,
    )
    expect(failing).toEqual([])
  })
})
