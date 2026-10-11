// Open Library covers by ISBN over a typographic cover (design doc §22.1). The typographic one
// is always drawn and the photo fades in on top once it has loaded, so a slow, throttled
// (Open Library allows 100 ISBN lookups per 5 minutes) or missing cover never shows as a blank.
import { useState } from 'react'

function hue(text: string): number {
  let h = 0
  for (const ch of text) h = (h * 31 + ch.charCodeAt(0)) % 360
  return h
}

export function Cover({ isbn, title, author }: { isbn: string; title: string; author: string }) {
  const [state, setState] = useState<'loading' | 'loaded' | 'failed'>('loading')
  const h = hue(title)
  return (
    <div className="relative aspect-[2/3] w-full overflow-hidden rounded-sm shadow-sm">
      <div
        aria-hidden="true"
        className="absolute inset-0 flex flex-col justify-between p-3 font-serif"
        style={{ background: `hsl(${h} 35% 32%)`, color: `hsl(${h} 40% 92%)` }}
      >
        <span className="line-clamp-5 text-sm leading-snug font-semibold">{title}</span>
        <span className="line-clamp-2 text-[11px] opacity-80">{author}</span>
      </div>
      {state !== 'failed' && /^\d{13}$/.test(isbn) && (
        <img
          src={`https://covers.openlibrary.org/b/isbn/${isbn}-M.jpg?default=false`}
          alt=""
          loading="lazy"
          onLoad={() => setState('loaded')}
          onError={() => setState('failed')}
          className={`absolute inset-0 size-full object-cover transition-opacity duration-500 ${state === 'loaded' ? 'opacity-100' : 'opacity-0'}`}
        />
      )}
    </div>
  )
}
