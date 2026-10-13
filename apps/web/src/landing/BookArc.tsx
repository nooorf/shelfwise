// The landing page's featured books on one arc (arc.ts): a dark far shelf of small covers in
// the middle, the character peeking over it, and the walls curving round to either side. On
// load the room opens from the middle outward. Pointing at or focusing a book tells the page
// (and so the character) which one; clicking opens it. Books are buttons in reading order.
import { forwardRef, useEffect, useState } from 'react'
import type { CSSProperties } from 'react'

import type { FeaturedBook } from '../api/types'
import { COVER, layout, order } from './arc'
import type { Placement } from './arc'

function coverUrl(id: number, size: 'M' | 'L'): string {
  return `https://covers.openlibrary.org/b/id/${id}-${size}.jpg`
}

function hue(text: string): number {
  let h = 0
  for (const ch of text) h = (h * 31 + ch.charCodeAt(0)) % 360
  return h
}

function byline(book: FeaturedBook): string {
  return `${book.title}${book.authors.length ? ` by ${book.authors.join(', ')}` : ''}`
}

interface CoverProps {
  book: FeaturedBook
  place: Placement
  index: number
  onOpen: () => void
  onPoint: (el: HTMLElement | null) => void
}

// The plain cover is always drawn and the photo fades in on top once it has loaded, so a slow
// or missing cover never leaves a gap in the arc.
function ArcCover({ book, place, index, onOpen, onPoint }: CoverProps) {
  const [cover, setCover] = useState<'loading' | 'loaded' | 'failed'>('loading')
  const big = place.scale > 0.9
  const style = {
    '--x': `${place.x}px`,
    '--s': place.scale,
    '--r': `${place.turn}deg`,
    '--i': index,
    zIndex: place.ring + 1,
  } as CSSProperties
  return (
    <button
      type="button"
      className="arc-book"
      data-side={place.side}
      style={style}
      onClick={onOpen}
      onPointerEnter={(e) => onPoint(e.currentTarget)}
      onPointerLeave={() => onPoint(null)}
      onFocus={(e) => onPoint(e.currentTarget)}
      onBlur={() => onPoint(null)}
      aria-label={byline(book)}
    >
      <span className="arc-plain" style={{ background: `hsl(${hue(book.title)} 32% 30%)` }} aria-hidden="true">
        <span className="arc-plain-title">{book.title}</span>
        <span className="arc-plain-author">{book.authors[0]}</span>
      </span>
      {cover !== 'failed' && (
        <img
          src={coverUrl(book.cover_id, big ? 'L' : 'M')}
          alt=""
          width={COVER.w}
          height={COVER.h}
          decoding="async"
          draggable={false}
          data-loaded={cover === 'loaded'}
          onLoad={() => setCover('loaded')}
          onError={() => setCover('failed')}
        />
      )}
    </button>
  )
}

interface Props {
  books: FeaturedBook[]
  horizon: number // y of the arc's middle line, in pixels from the top of the arc's box
  onOpen: (book: FeaturedBook) => void
  onPoint: (book: FeaturedBook | null, el: HTMLElement | null) => void
}

export const BookArc = forwardRef<HTMLDivElement, Props>(function BookArc({ books, horizon, onOpen, onPoint }, ref) {
  const [box, setBox] = useState({ width: 0, height: 0 })
  const [element, setElement] = useState<HTMLDivElement | null>(null)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (!element) return
    const measure = () => setBox({ width: element.clientWidth, height: element.clientHeight })
    measure()
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => observer.disconnect()
  }, [element])

  // Open the room once the books are there (two frames, so the closed state paints first).
  useEffect(() => {
    if (books.length === 0) return
    let second = 0
    const first = requestAnimationFrame(() => {
      second = requestAnimationFrame(() => setOpen(true))
    })
    return () => {
      cancelAnimationFrame(first)
      cancelAnimationFrame(second)
    }
  }, [books.length])

  // Until the box is measured (and where nothing is, as in tests), lay out for the design size.
  const arc = layout(box.width || 1440, box.height || 820, books.length)
  const shelfStyle = { width: arc.shelf.width, height: arc.shelf.height, '--u': arc.unit } as CSSProperties

  return (
    <div
      ref={(el) => {
        setElement(el)
        if (typeof ref === 'function') ref(el)
        else if (ref) ref.current = el
      }}
      className={`arc ${open ? 'is-open' : ''}`}
      style={{ '--horizon': `${horizon}px` } as CSSProperties}
      role="region"
      aria-label="Featured books"
    >
      {books.length > 0 && <div className="arc-shelf" style={shelfStyle} aria-hidden="true" />}
      {order(arc.places).map((i) => (
        <ArcCover
          key={books[i].work_id}
          book={books[i]}
          place={arc.places[i]}
          index={arc.places[i].ring}
          onOpen={() => onOpen(books[i])}
          onPoint={(el) => onPoint(el ? books[i] : null, el)}
        />
      ))}
    </div>
  )
})
