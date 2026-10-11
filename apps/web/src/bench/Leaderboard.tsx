// One row per system, best first: nDCG@10 as a dot on its 95% CI, then the other metrics.
// The table is the chart's own table view: every number is in a cell.
import type { SystemScore } from '../api/types'
import { SHIPPED } from './scales'

const W = 220 // px for the 0..1 interval strip

export function Leaderboard({ systems }: { systems: SystemScore[] }) {
  const x = (v: number) => 4 + v * (W - 8)
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-sm">
        <thead className="text-left text-muted">
          <tr>
            <th className="py-1 pr-3 font-medium">System</th>
            <th className="py-1 pr-3 font-medium">nDCG@10</th>
            <th className="py-1 pr-3 font-medium" aria-hidden="true" />
            <th className="py-1 pr-3 text-right font-medium">Recall@10</th>
            <th className="py-1 pr-3 text-right font-medium">MRR</th>
            <th className="py-1 pr-3 text-right font-medium">Judged</th>
            <th className="py-1 text-right font-medium">p95 ms</th>
          </tr>
        </thead>
        <tbody>
          {systems.map((s) => {
            const [low, high] = s.ndcg.ci95
            return (
              <tr key={s.name} className="border-t border-line">
                <th scope="row" className="py-1.5 pr-3 text-left font-normal">
                  <code>{s.name}</code>
                  {s.name === SHIPPED && <span className="bench-badge">in the app</span>}
                </th>
                <td className="py-1.5 pr-3 tabular-nums">
                  {s.ndcg.mean.toFixed(3)} <span className="text-muted">[{low.toFixed(2)}–{high.toFixed(2)}]</span>
                </td>
                <td className="py-1.5 pr-3" aria-hidden="true">
                  <svg width={W} height={16} className="block">
                    <line x1={x(0)} x2={x(1)} y1={8} y2={8} stroke="var(--color-line)" strokeWidth={1} />
                    <line x1={x(low)} x2={x(high)} y1={8} y2={8} stroke="var(--color-seq-9)" strokeWidth={2} strokeLinecap="round" />
                    <circle cx={x(s.ndcg.mean)} cy={8} r={4} fill="var(--color-seq-9)" stroke="var(--color-paper)" strokeWidth={2} />
                  </svg>
                </td>
                <td className="py-1.5 pr-3 text-right tabular-nums">{s.recall.toFixed(3)}</td>
                <td className="py-1.5 pr-3 text-right tabular-nums">{s.mrr.toFixed(3)}</td>
                <td className="py-1.5 pr-3 text-right tabular-nums">{Math.round(s.judged * 100)}%</td>
                <td className="py-1.5 text-right tabular-nums">{s.latency_ms?.p95 ?? '—'}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
