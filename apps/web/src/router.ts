// Four pages, no router library: the landing page, text chat, the live session and the bench.
// Links push history entries; the back button works through popstate.
import { useEffect, useState } from 'react'

export type Page = 'landing' | 'chat' | 'live' | 'bench'

export function pageFor(pathname: string): Page {
  if (pathname.startsWith('/bench')) return 'bench'
  if (pathname.startsWith('/chat')) return 'chat'
  if (pathname.startsWith('/live')) return 'live'
  return 'landing'
}

export function navigate(path: string): void {
  if (window.location.pathname === path) return
  window.history.pushState(null, '', path)
  window.dispatchEvent(new PopStateEvent('popstate'))
  window.scrollTo(0, 0)
}

export function usePage(): Page {
  const [page, setPage] = useState(() => pageFor(window.location.pathname))
  useEffect(() => {
    const update = () => setPage(pageFor(window.location.pathname))
    window.addEventListener('popstate', update)
    return () => window.removeEventListener('popstate', update)
  }, [])
  return page
}
