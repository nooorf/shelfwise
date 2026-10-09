// Explore (design doc §22.3): pick a genre to browse it, books on the shelf now and the most
// borrowed first. The genres and their counts come from the catalog.
import { useEffect, useState } from 'react'

import { getGenres } from '../api/client'
import type { GenreCount } from '../api/types'

export function ExplorePanel({ onExplore }: { onExplore: (genre: string) => void }) {
  const [genres, setGenres] = useState<GenreCount[] | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let live = true
    getGenres()
      .then((found) => live && setGenres(found))
      .catch(() => live && setFailed(true))
    return () => {
      live = false
    }
  }, [])

  if (failed) return <p className="text-sm text-out">Couldn’t load the genres. Try again in a moment.</p>
  if (!genres) return <p className="text-sm text-muted">Loading genres…</p>
  return (
    <ul aria-label="Genres" className="flex flex-wrap gap-1.5">
      {genres.map((g) => (
        <li key={g.name}>
          <button
            type="button"
            onClick={() => onExplore(g.name)}
            className="rounded-full border border-line px-3 py-1 text-sm capitalize hover:border-accent hover:text-accent focus-visible:outline-2 focus-visible:outline-accent"
          >
            {g.name} <span className="text-muted tabular-nums">{g.books.toLocaleString()}</span>
          </button>
        </li>
      ))}
    </ul>
  )
}
