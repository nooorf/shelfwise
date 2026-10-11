// The live session, measured (`make measure`, design doc §21, §32): how long after a spoken
// question the first word of the answer is heard, stage by stage, whether the avatar costs
// any of it, how well its lips keep time with the sound, its frame rate and load time.
import { useState } from 'react'

import type { Bench } from '../api/types'
import { niceStep, waterfall } from './scales'

type Voice = NonNullable<Bench['voice']>
type Condition = Voice['on']

const STAGES = [
  ['endpoint', 'Hearing the end', 'the voice detector waits for 600 ms of silence'],
  ['transcribe', 'Transcribing', 'Whisper large-v3-turbo, with names put back to the catalog’s spelling'],
  ['parse', 'Understanding', 'the query parser reads the request into constraints'],
  ['retrieve', 'Searching', 'filters, hybrid search, live availability'],
  ['voice', 'Voicing the first sentence', 'Kokoro turns the opening into speech'],
  ['playback', 'Playback', 'sent, decoded, scheduled, and through the audio output'],
  ['handoffs', 'Handoffs', 'between the stages: the socket and threads'],
] as const
type Stage = (typeof STAGES)[number][0]

const seconds = (ms: number) => `${(ms / 1000).toFixed(ms < 10_000 ? 2 : 1)} s`
const signed = (ms: number) => `${ms > 0 ? '+' : ms < 0 ? '−' : ''}${Math.abs(Math.round(ms))} ms`

function Stat({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return (
    <div className="stat">
      <p className="stat-label">{label}</p>
      <p className="stat-value">{value}</p>
      {detail && <p className="stat-detail">{detail}</p>}
    </div>
  )
}

function Waterfall({ condition }: { condition: Condition }) {
  const [hover, setHover] = useState<Stage | null>(null)
  const stages = condition.stages
  if (!stages || !condition.ttfa) return null
  const bars = waterfall(STAGES.map(([key]) => key), stages as Record<Stage, number>)
  const total = bars.at(-1)?.end ?? 0
  const step = niceStep(total)
  const ticks = Array.from({ length: Math.floor(total / step) + 1 }, (_, i) => i * step)
  const top = Math.max(total, ticks.at(-1) ?? 0)
  const pct = (ms: number) => `${(ms / top) * 100}%`

  return (
    <figure className="waterfall">
      <div className="waterfall-rows" onMouseLeave={() => setHover(null)}>
        {STAGES.map(([key, name, what], i) => {
          const bar = bars[i]
          const ms = bar.end - bar.start
          return (
            <div key={key} className="waterfall-row" data-hover={hover === key || undefined}>
              <span className="waterfall-name">{name}</span>
              <span className="waterfall-track">
                {ticks.map((t) => (
                  <span key={t} className="waterfall-grid" style={{ left: pct(t) }} aria-hidden="true" />
                ))}
                <span
                  className="waterfall-bar"
                  style={{ left: pct(bar.start), width: `max(2px, ${pct(ms)})` }}
                  tabIndex={0}
                  role="img"
                  aria-label={`${name}: ${Math.round(ms)} ms, ${what}`}
                  onMouseEnter={() => setHover(key)}
                  onFocus={() => setHover(key)}
                  onBlur={() => setHover(null)}
                />
                {hover === key && (
                  <span role="status" className="waterfall-tip" style={{ left: pct(bar.end) }}>
                    <strong>{name}</strong> {Math.round(ms)} ms · {Math.round((ms / total) * 100)}% of the wait
                    <br />
                    {what}; starts at {Math.round(bar.start)} ms
                  </span>
                )}
              </span>
              <span className="waterfall-value">{Math.round(ms)} ms</span>
            </div>
          )
        })}
        <div className="waterfall-row is-total">
          <span className="waterfall-name">First word heard</span>
          <span className="waterfall-track">
            <span className="waterfall-mark" style={{ left: pct(total) }} aria-hidden="true" />
          </span>
          <span className="waterfall-value">{seconds(total)}</span>
        </div>
        <div className="waterfall-row is-axis" aria-hidden="true">
          <span />
          <span className="waterfall-track">
            {ticks.map((t) => (
              <span key={t} className="waterfall-tick" style={{ left: pct(t) }}>
                {t === 0 ? '0' : `${t / 1000} s`}
              </span>
            ))}
          </span>
          <span />
        </div>
      </div>
      <figcaption>
        Mean time per stage over {condition.answered} spoken questions, from the end of the question’s last word;
        the means add up to the mean wait. Median {seconds(condition.ttfa.p50)}, p95 {seconds(condition.ttfa.p95)}.
      </figcaption>
    </figure>
  )
}

export function VoicePanel({ voice }: { voice: Voice }) {
  const { on, off, avatar_cost_ms: cost, avatar_load: load } = voice
  const shown = on.ttfa ? on : off
  return (
    <div className="flex flex-col gap-5">
      <div className="stats is-small is-three">
        {shown.ttfa && (
          <Stat
            label="Time to first audio, median"
            value={seconds(shown.ttfa.p50)}
            detail={`p95 ${seconds(shown.ttfa.p95)}; from the last word of the question to the first word of the answer`}
          />
        )}
        {cost && (
          <Stat
            label="What the avatar adds to it"
            value={signed(cost.mean)}
            detail={
              cost.ci95
                ? `mean over the same ${cost.n} questions, avatar on vs off; 95% CI ${signed(cost.ci95[0])} to ${signed(cost.ci95[1])}`
                : `mean over the same ${cost.n} questions, avatar on vs off`
            }
          />
        )}
        {on.av_offset && (
          <Stat
            label="Lip-sync offset, median"
            value={signed(on.av_offset.p50)}
            detail={`95% within ±${Math.round(on.av_offset.abs_p95)} ms; positive: the lips follow the sound`}
          />
        )}
        {on.fps && (
          <Stat
            label="Avatar frame rate while speaking"
            value={`${Math.round(on.fps.p50)} fps`}
            detail={on.fps_p5 != null ? `the slowest 5% of answers: ${Math.round(on.fps_p5)} fps` : undefined}
          />
        )}
        {load.first_frame_ms && (
          <Stat
            label="Avatar load, cold cache"
            value={seconds(load.first_frame_ms.p50)}
            detail={`median from opening the page to its first frame${load.model_ms ? `; the model alone ${seconds(load.model_ms.p50)}` : ''}`}
          />
        )}
        {shown.first_note && (
          <Stat
            label="First book note on screen"
            value={seconds(shown.first_note.p50)}
            detail="median; the LLM’s words, after the spoken opening"
          />
        )}
      </div>
      <Waterfall condition={shown} />
      <p className="bench-meta">
        Parser {voice.parser ?? '?'} · {voice.browser} · {voice.machine} · avatar {voice.avatar_model} · {voice.git} ·{' '}
        {new Date(voice.created).toLocaleString()}. Measured in the page: questions in the assistant’s own voice through
        a stand-in microphone; sound from the audio clock’s output timestamps; the lips from the avatar’s render loop.
      </p>
    </div>
  )
}
