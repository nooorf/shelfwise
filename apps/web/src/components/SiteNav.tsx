// The reading room's header (landing, chat, live): the dark pill with the mark and a menu of
// the pages on the left, the page's own actions on the right. Styles in styles/site.css.
import { Menu, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'

import { Link } from './Link'

export function Mark() {
  // Three spines, the last one leaning: the only drawing on the page.
  return (
    <svg viewBox="0 0 20 20" className="size-5" aria-hidden="true">
      <rect x="2" y="4" width="3.4" height="13" rx="0.6" fill="currentColor" />
      <rect x="6.6" y="2" width="3.4" height="15" rx="0.6" fill="currentColor" />
      <rect x="12.2" y="3.4" width="3.4" height="13.6" rx="0.6" fill="currentColor" transform="rotate(-16 13.9 17)" />
    </svg>
  )
}

function NavMenu() {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const away = (e: PointerEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false)
    }
    const escape = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('pointerdown', away)
    document.addEventListener('keydown', escape)
    return () => {
      document.removeEventListener('pointerdown', away)
      document.removeEventListener('keydown', escape)
    }
  }, [open])
  return (
    <div ref={box} className="nav-pill">
      <Link href="/" className="nav-brand">
        <Mark />
        Shelfwise
      </Link>
      <button
        type="button"
        className="nav-toggle"
        aria-expanded={open}
        aria-controls="nav-menu"
        aria-label={open ? 'Close menu' : 'Menu'}
        onClick={() => setOpen((o) => !o)}
      >
        {open ? <X className="size-4" aria-hidden="true" /> : <Menu className="size-4" aria-hidden="true" />}
      </button>
      {open && (
        <ul id="nav-menu" className="nav-menu">
          <li><Link href="/chat">Chat</Link></li>
          <li><Link href="/live">Live session</Link></li>
          <li><Link href="/bench">Benchmarks</Link></li>
        </ul>
      )}
    </div>
  )
}

export function SiteNav({ children, className = '' }: { children?: ReactNode; className?: string }) {
  return (
    <header className={`nav ${className}`}>
      <NavMenu />
      {children && (
        <nav aria-label="Pages" className="nav-actions">
          {children}
        </nav>
      )}
    </header>
  )
}
