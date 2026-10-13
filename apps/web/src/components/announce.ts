// What a screen reader hears after a turn: the notes, how many books and
// the first few titles, then the reply's opening line once it's written. One sentence group
// per turn, so the reader isn't interrupted by every state change.
import type { Exchange } from '../session/store'

const SHELF = new Set(['search', 'surprise', 'explain', 'compare'])
const NAMED = 3

export function announcement(e: Exchange | undefined): string {
  if (!e) return ''
  if (e.cancelled) return 'Stopped.'
  const r = e.response
  if (!r) return e.pending ? 'Looking…' : ''
  const parts = [...r.notes]
  if (SHELF.has(r.route) && r.results.length > 0) {
    const n = r.results.length
    const titles = r.results.slice(0, NAMED).map((b) => b.title).join('; ')
    parts.push(`${n} ${n === 1 ? 'book' : 'books'}: ${titles}${n > NAMED ? '; and more' : ''}.`)
  }
  if (e.reply?.intro) parts.push(e.reply.intro)
  return parts.join(' ')
}
