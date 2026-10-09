import { describe, expect, it } from 'vitest'

import { findModel, orbReason } from './choice'

const ok = { wanted: true, reducedMotion: false, webgl: true, model: '/avatar/sample.vrm', failed: null }

describe('avatar or orb', () => {
  it('shows the avatar only when everything allows it', () => {
    expect(orbReason(ok)).toBeNull()
    expect(orbReason({ ...ok, wanted: false })).toBe('off')
    expect(orbReason({ ...ok, reducedMotion: true })).toBe('reduced-motion')
    expect(orbReason({ ...ok, webgl: false })).toBe('no-webgl')
    expect(orbReason({ ...ok, model: null })).toBe('missing')
    expect(orbReason({ ...ok, failed: 'slow' })).toBe('slow')
  })

  it('prefers your own model and ignores a dev server’s HTML fallback', async () => {
    const serve = (types: Record<string, string>) =>
      (async (url: string) =>
        new Response(null, { status: 200, headers: { 'content-type': types[url] ?? 'text/html' } })) as typeof fetch

    expect(await findModel(serve({ '/avatar/sample.vrm': 'application/octet-stream' }))).toBe('/avatar/sample.vrm')
    expect(await findModel(serve({ '/avatar/shelfwise.vrm': 'model/vrm', '/avatar/sample.vrm': 'model/vrm' }))).toBe(
      '/avatar/shelfwise.vrm',
    )
    expect(await findModel(serve({}))).toBeNull()
  })
})
