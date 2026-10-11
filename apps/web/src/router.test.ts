import { describe, expect, it, vi } from 'vitest'

import { navigate, pageFor } from './router'

describe('router', () => {
  it('maps paths to pages, the landing page by default', () => {
    expect(pageFor('/')).toBe('landing')
    expect(pageFor('/chat')).toBe('chat')
    expect(pageFor('/live')).toBe('live')
    expect(pageFor('/bench')).toBe('bench')
    expect(pageFor('/anything-else')).toBe('landing')
  })

  it('navigates without reloading and tells listeners', () => {
    const listener = vi.fn()
    window.addEventListener('popstate', listener)
    navigate('/chat')
    expect(window.location.pathname).toBe('/chat')
    expect(listener).toHaveBeenCalledTimes(1)
    navigate('/chat') // already there: nothing happens
    expect(listener).toHaveBeenCalledTimes(1)
    window.removeEventListener('popstate', listener)
    navigate('/')
  })
})
