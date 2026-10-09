// nDCG@10 per system and query category: a table whose cells take a sequential blue by score
// (darker = better in light mode; brighter on dark), with the number in every cell.
import type { SystemScore } from '../api/types'
import { step } from './scales'

const label = (category: string) => category.replace('_', ' ')

export function CategoryHeatmap({ systems }: { systems: SystemScore[] }) {
  const categories = [...new Set(systems.flatMap((s) => Object.keys(s.by_category)))].sort()
  return (
    <div className="overflow-x-auto">
      <table className="border-separate border-spacing-0.5 text-xs">
        <thead>
          <tr>
            <th className="pr-2 text-left font-medium text-muted">System</th>
            {categories.map((c) => (
              <th key={c} scope="col" className="px-1 pb-1 align-bottom font-medium text-muted capitalize">{label(c)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {systems.map((s) => (
            <tr key={s.name}>
              <th scope="row" className="pr-2 text-left font-normal"><code>{s.name}</code></th>
              {categories.map((c) => {
                const v = s.by_category[c]
                if (v == null) return <td key={c} className="text-center text-muted">—</td>
                const n = step(v)
                return (
                  <td key={c} title={`${s.name} · ${label(c)}: ${v.toFixed(3)}`}
                      className="min-w-12 rounded-sm px-2 py-1.5 text-center tabular-nums"
                      style={{ background: `var(--color-seq-${n})`, color: `var(--color-seq-ink-${n})` }}>
                    {v.toFixed(2)}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
