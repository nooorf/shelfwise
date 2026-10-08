// Open Library covers by ISBN, with a typographic cover when there's none (design doc §22.1).
import { useState } from 'react'

function hue(text: string): number {
  let h = 0
  for (const ch of text) h = (h * 31 + ch.charCodeAt(0)) % 360
  return h
}

export function Cover({ isbn, title, author }: { isbn: string; title: string; author: string }) {
  const [failed, setFailed] = useState(false)
  if (!failed && /^\d{13}$/.test(isbn)) {
    return (
      <img
        src={`https://covers.openlibrary.org/b/isbn/${isbn}-M.jpg?default=false`}
        alt=""
        loading="lazy"
        onError={() => setFailed(true)}
        className="aspect-[2/3] w-full rounded-sm object-cover shadow-sm"
      />
    )
  }
  const h = hue(title)
  return (
    <div
      aria-hidden="true"
      className="flex aspect-[2/3] w-full flex-col justify-between rounded-sm p-3 font-serif shadow-sm"
      style={{ background: `hsl(${h} 35% 32%)`, color: `hsl(${h} 40% 92%)` }}
    >
      <span className="line-clamp-5 text-sm leading-snug font-semibold">{title}</span>
      <span className="line-clamp-2 text-[11px] opacity-80">{author}</span>
    </div>
  )
}
