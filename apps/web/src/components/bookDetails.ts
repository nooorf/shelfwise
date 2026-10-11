// The drawer's record in words, testable without rendering. Tags come from the book's
// description (an LLM read it), so they are worded as a guide, not as fact.
import type { BookDetail } from '../api/types'
import { dueLabel } from './availability'

const SCALES: Record<string, [string, string[]]> = {
  darkness: ['Tone', ['Light', 'Some dark moments', 'Dark', 'Very dark']],
  romance: ['Romance', ['None', 'A minor thread', 'A main thread', 'At its heart']],
  violence: ['Violence', ['None', 'Mild', 'On the page', 'Graphic']],
}
const WORDS: Record<string, [string, Record<string, string>]> = {
  pace: ['Pace', { slow: 'Slow burn', medium: 'Steady', fast: 'Fast' }],
  supernatural: ['Supernatural', { yes: 'Yes', no: 'No' }],
  audience: ['For', { children: 'Children', ya: 'Teens (YA)', adult: 'Adults' }],
  reading_level: ['Level', { intro: 'Beginner', intermediate: 'Intermediate', advanced: 'Advanced' }],
}

/** [label, value] pairs for the tags the book has; unknown ones are left out. */
export function tagLines(tags: BookDetail['tags']): [string, string][] {
  const lines: [string, string][] = []
  for (const [key, [label, levels]] of Object.entries(SCALES)) {
    const value = tags[key]
    if (typeof value === 'number' && levels[value]) lines.push([label, levels[value]])
  }
  for (const [key, [label, words]] of Object.entries(WORDS)) {
    const value = tags[key]
    if (typeof value === 'string' && words[value]) lines.push([label, words[value]])
  }
  if (typeof tags.fiction === 'boolean') lines.push(['Kind', tags.fiction ? 'Fiction' : 'Nonfiction'])
  if (tags.historical_setting === 'yes') {
    lines.push(['Set in', typeof tags.setting_period === 'string' ? tags.setting_period : 'The past'])
  }
  return lines
}

const STATUS: Record<string, string> = {
  available: 'On the shelf',
  on_hold: 'On hold for someone',
  in_transit: 'Between branches',
  reference_only: 'Reference only: read it here',
  repair: 'Being repaired',
}

/** One copy in words: where it is and whether you can have it. */
export function copyLine(copy: BookDetail['copies'][number], today?: Date): string {
  const where = [copy.branch, copy.floor && `Floor ${copy.floor}`, copy.call_number]
    .filter(Boolean)
    .join(' · ')
  const status =
    copy.status === 'on_loan'
      ? copy.due_date
        ? `Borrowed, ${dueLabel(copy.due_date, today).replace(/^Due/, 'due')}`
        : 'Borrowed'
      : (STATUS[copy.status] ?? copy.status)
  return `${status} — ${where}`
}

/** The title without its subtitle, for one-line captions: "Wicked: The Life and Times of the
 * Wicked Witch of the West" is "Wicked". A head too short to stand alone ("Y: The Last Man")
 * keeps the whole title. */
export function shortTitle(title: string): string {
  const head = title.split(': ')[0]
  return head.length >= 4 ? head : title
}
