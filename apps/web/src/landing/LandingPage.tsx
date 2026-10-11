// The front door, as a round reading room seen from its doorway: the featured books on one
// arc around the visitor (BookArc), the assistant peeking over the far shelf (Character,
// lazy-loaded; skipped on small screens, without WebGL or with reduced motion), and a box
// that takes a request in your own words and opens the chat with it. Below: one request
// taken apart into what it must and would prefer to have, then the live session.
import { AudioLines } from 'lucide-react'
import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react'
import type { CSSProperties, ReactNode, RefObject } from 'react'

import { getFeatured } from '../api/client'
import type { FeaturedBook } from '../api/types'
import { findModel, hasWebGL } from '../avatar/choice'
import { availabilityText } from '../components/availability'
import { BookDrawer } from '../components/BookDrawer'
import { shortTitle } from '../components/bookDetails'
import { Link } from '../components/Link'
import { Mark, SiteNav } from '../components/SiteNav'
import { AskBox } from './AskBox'
import { BookArc } from './BookArc'
import '../styles/site.css'
import './landing.css'

const Character = lazy(() => import('./Character'))

const HORIZON = 0.7 // the arc's middle line, as a fraction down the stage

function useCharacterModel(): string | null {
  const [model, setModel] = useState<string | null>(null)
  useEffect(() => {
    const wide = globalThis.matchMedia?.('(min-width: 768px)').matches ?? false
    const still = globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
    if (!wide || still || !hasWebGL()) return
    let live = true
    void findModel().then((url) => live && setModel(url))
    return () => {
      live = false
    }
  }, [])
  return model
}

/** The arc's middle line (HORIZON down the stage) in the hero's coordinates, kept up to date. */
function useHorizon(hero: RefObject<HTMLElement | null>, stage: RefObject<HTMLElement | null>) {
  const [horizon, setHorizon] = useState(0)
  useEffect(() => {
    const measure = () => {
      if (!hero.current || !stage.current) return
      const h = hero.current.getBoundingClientRect()
      const s = stage.current.getBoundingClientRect()
      setHorizon(s.top - h.top + s.height * HORIZON)
    }
    measure()
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(measure)
    if (hero.current) observer.observe(hero.current)
    if (stage.current) observer.observe(stage.current)
    return () => observer.disconnect()
  }, [hero, stage])
  return horizon
}

function Caption({ book }: { book: FeaturedBook | null }) {
  return (
    <p className={`arc-caption ${book ? 'is-shown' : ''}`} aria-hidden="true">
      {book && (
        <>
          <span className="arc-caption-title">{shortTitle(book.title)}</span>
          {book.authors[0] && <span>{book.authors[0]}</span>}
          <span className="arc-caption-state" data-state={book.availability.state}>
            {availabilityText(book.availability)}
          </span>
        </>
      )}
    </p>
  )
}

function Phrase({ kind, children }: { kind: 'must' | 'prefer' | 'never'; children: ReactNode }) {
  return <span className={`phrase phrase-${kind}`}>{children}</span>
}

/** One real request taken apart the way the search reads it. Underlines draw in when it
 * comes into view; without motion they are simply there. */
function Parse() {
  const section = useRef<HTMLElement>(null)
  const [seen, setSeen] = useState(false)
  useEffect(() => {
    const element = section.current
    if (!element || typeof IntersectionObserver === 'undefined') {
      setSeen(true)
      return
    }
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setSeen(true)
          observer.disconnect()
        }
      },
      { threshold: 0.35 },
    )
    observer.observe(element)
    return () => observer.disconnect()
  }, [])
  return (
    <section ref={section} className={`parse ${seen ? 'is-seen' : ''}`} aria-labelledby="parse-title">
      <div className="parse-inner">
        <blockquote className="parse-request">
          <p>
            “<Phrase kind="prefer">Dark</Phrase> and <Phrase kind="prefer">psychological</Phrase>,{' '}
            <Phrase kind="never">nothing supernatural</Phrase>, <Phrase kind="must">under 300 pages</Phrase>,{' '}
            <Phrase kind="must">on the shelf today</Phrase>.”
          </p>
        </blockquote>

        <div className="parse-chips">
          <div>
            <p id="chips-must">Must</p>
            <ul aria-labelledby="chips-must">
              <li className="chip chip-must">under 300 pages</li>
              <li className="chip chip-must">available now</li>
              <li className="chip chip-never">no supernatural</li>
            </ul>
          </div>
          <div>
            <p id="chips-preferred">Preferred</p>
            <ul aria-labelledby="chips-preferred">
              <li className="chip chip-prefer">dark</li>
              <li className="chip chip-prefer">psychological</li>
            </ul>
          </div>
        </div>

        <div className="parse-copy">
          <h2 id="parse-title">Limits stay limits.</h2>
          <p>
            Shelfwise sorts a request into what you need and what you’d like. A book that breaks
            one of your limits is never shown, and every book it names is one the search found.
          </p>
        </div>
      </div>
    </section>
  )
}

export function LandingPage() {
  const [books, setBooks] = useState<FeaturedBook[]>([])
  const [open, setOpen] = useState<FeaturedBook | null>(null)
  const [pointedBook, setPointedBook] = useState<FeaturedBook | null>(null)
  const [characterShown, setCharacterShown] = useState(false)
  const hero = useRef<HTMLElement>(null)
  const stage = useRef<HTMLDivElement>(null)
  const arc = useRef<HTMLDivElement>(null)
  const pointed = useRef<HTMLElement | null>(null)
  const horizon = useHorizon(hero, stage)
  const model = useCharacterModel()
  const onReady = useCallback(() => setCharacterShown(true), [])
  const onFailed = useCallback(() => setCharacterShown(false), [])
  const onPoint = useCallback((book: FeaturedBook | null, el: HTMLElement | null) => {
    pointed.current = el
    setPointedBook(book)
  }, [])

  useEffect(() => {
    let live = true
    getFeatured()
      .then((list) => live && setBooks(list))
      .catch(() => live && setBooks([]))
    return () => {
      live = false
    }
  }, [])

  return (
    <div className="reading-room site landing">
      <section ref={hero} className={`hero ${model ? 'has-character' : ''}`}>
        {model && horizon > 0 && (
          // Behind the arc, so the far shelf hides everything below the character's shoulders.
          <div
            className={`character ${characterShown ? 'is-ready' : ''}`}
            style={{ '--horizon': `${horizon}px` } as CSSProperties}
            data-character={characterShown ? 'ready' : 'loading'}
          >
            <Suspense fallback={null}>
              <Character url={model} arc={arc} pointed={pointed} onReady={onReady} onFailed={onFailed} />
            </Suspense>
          </div>
        )}
        <BookArc ref={arc} books={books} horizon={horizon} onOpen={setOpen} onPoint={onPoint} />

        <SiteNav>
          <Link href="/bench" className="btn btn-butter">Benchmarks</Link>
          <Link href="/live" className="btn btn-coral">Live session</Link>
        </SiteNav>

        <div className="hero-copy">
          <h1 className="hero-title">
            Describe a mood.
            <br />
            Find it on the shelf.
          </h1>

          <div ref={stage} className="hero-stage" />

          <Caption book={pointedBook} />
          <p className="hero-sub">
            Ask the way you’d ask a librarian. Shelfwise only suggests books this library owns,
            and shows which are in today.
          </p>
          <AskBox />
        </div>
      </section>

      <Parse />

      <section className="close" aria-labelledby="close-title">
        <h2 id="close-title">Or say it out loud.</h2>
        <div className="close-side">
          <p>The live session listens, answers in a voice, and puts the books on screen while it talks.</p>
          <Link href="/live" className="btn btn-coral btn-lg">
            <AudioLines className="size-4" aria-hidden="true" /> Live session
          </Link>
        </div>
      </section>

      <footer className="foot">
        <span className="foot-brand"><Mark /> Shelfwise</span>
        <p>Book data from Open Library and the UCSD Book Graph. Covers from Open Library.</p>
        <Link href="/bench">Benchmarks</Link>
      </footer>

      {open && <BookDrawer key={open.work_id} book={open} onClose={() => setOpen(null)} />}
    </div>
  )
}
