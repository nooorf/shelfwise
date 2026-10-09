// Quality (nDCG@10) against p95 latency, one dot per system. Systems on the Pareto front are
// joined by a step line and labelled; every dot shows its numbers on hover or focus.
import { useState } from 'react'

import type { SystemScore } from '../api/types'
import { logScale, logTicks, paretoFront, SHIPPED } from './scales'

const W = 640
const H = 300
const M = { top: 16, right: 24, bottom: 40, left: 48 }

type Timed = SystemScore & { latency_ms: { p50: number; p95: number } }

export function ParetoChart({ systems }: { systems: SystemScore[] }) {
  const [hover, setHover] = useState<Timed | null>(null)
  const timed = systems.filter((s): s is Timed => s.latency_ms != null)
  if (timed.length === 0) {
    return <p className="text-sm text-muted">This report has no latencies: re-run <code>make eval</code>.</p>
  }
  const p95 = timed.map((s) => s.latency_ms.p95)
  const lo = 10 ** Math.floor(Math.log10(Math.max(Math.min(...p95), 0.1)))
  const hi = 10 ** Math.ceil(Math.log10(Math.max(...p95)))
  const x = logScale(lo, hi, M.left, W - M.right)
  const y = (v: number) => H - M.bottom - v * (H - M.top - M.bottom)
  const front = paretoFront(timed, (s) => s.ndcg.mean, (s) => s.latency_ms.p95)
  const onFront = new Set(front.map((s) => s.name))
  const steps = front.flatMap((s, i) => {
    const point = `${x(s.latency_ms.p95)},${y(s.ndcg.mean)}`
    return i === 0 ? [point] : [`${x(s.latency_ms.p95)},${y(front[i - 1].ndcg.mean)}`, point]
  })

  return (
    <div className="relative max-w-full overflow-x-auto">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full min-w-[480px]" role="img"
           aria-label="nDCG@10 against p95 latency per system; the leaderboard table has the same numbers">
        {[0, 0.25, 0.5, 0.75, 1].map((v) => (
          <g key={v}>
            <line x1={M.left} x2={W - M.right} y1={y(v)} y2={y(v)} stroke="var(--color-line)" strokeWidth={1} />
            <text x={M.left - 8} y={y(v)} dy="0.32em" textAnchor="end" className="fill-muted text-[11px] tabular-nums">{v}</text>
          </g>
        ))}
        {logTicks(lo, hi).map((v) => (
          <text key={v} x={x(v)} y={H - M.bottom + 16} textAnchor="middle" className="fill-muted text-[11px] tabular-nums">
            {v >= 1 ? v : v.toFixed(1)} ms
          </text>
        ))}
        <text x={(M.left + W - M.right) / 2} y={H - 6} textAnchor="middle" className="fill-muted text-[11px]">p95 latency (log)</text>
        <text transform={`translate(12 ${(M.top + H - M.bottom) / 2}) rotate(-90)`} textAnchor="middle" className="fill-muted text-[11px]">nDCG@10</text>
        <polyline points={steps.join(' ')} fill="none" stroke="var(--color-seq-9)" strokeWidth={2} strokeOpacity={0.5} />
        {timed.map((s) => {
          const cx = x(s.latency_ms.p95)
          const cy = y(s.ndcg.mean)
          return (
            <g key={s.name} tabIndex={0} role="img" aria-label={`${s.name}: nDCG@10 ${s.ndcg.mean.toFixed(3)}, p95 ${s.latency_ms.p95} ms`}
               onMouseEnter={() => setHover(s)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(s)} onBlur={() => setHover(null)}
               className="cursor-default outline-none">
              <circle cx={cx} cy={cy} r={12} fill="transparent" />
              <circle cx={cx} cy={cy} r={hover?.name === s.name ? 6 : 4.5}
                      fill={onFront.has(s.name) ? 'var(--color-seq-9)' : 'var(--color-seq-4)'}
                      stroke="var(--color-paper)" strokeWidth={2} />
              {(onFront.has(s.name) || s.name === SHIPPED) && (
                <text x={cx + 8} y={cy - 8} className={`fill-ink text-[11px] ${s.name === SHIPPED ? 'font-semibold' : ''}`}>{s.name}</text>
              )}
            </g>
          )
        })}
      </svg>
      {hover && (
        <div role="status" className="pointer-events-none absolute top-2 right-2 rounded-md border border-line bg-card px-3 py-2 text-xs shadow-sm tabular-nums">
          <p className="font-semibold"><code>{hover.name}</code></p>
          <p>nDCG@10 {hover.ndcg.mean.toFixed(3)} [{hover.ndcg.ci95[0].toFixed(2)}–{hover.ndcg.ci95[1].toFixed(2)}]</p>
          <p>p50 {hover.latency_ms.p50} ms · p95 {hover.latency_ms.p95} ms</p>
        </div>
      )}
    </div>
  )
}
