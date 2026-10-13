// Grounding: what each system says that it shouldn't, as a share of its
// answers on set E. The headline is the Shelfwise row: invented books that reached a reader,
// against how many its validator caught in the first drafts.
import type { Bench } from '../api/types'

type Grounding = NonNullable<Bench['grounding']>

const NAMES: Record<string, string> = {
  llm_only: 'LLM only (own memory)',
  naive_rag: 'Naive RAG (top 5, no checks)',
  full: 'Shelfwise',
}

const pct = (v: number | null | undefined) => (v == null ? '—' : `${(v * 100).toFixed(1)}%`)

export function GroundingTable({ grounding }: { grounding: Grounding }) {
  const full = grounding.systems.find((s) => s.name === 'full')
  return (
    <div className="flex flex-col gap-3">
      {full && (
        <p className="text-sm">
          Invented books shown to readers: <strong>{pct(full.invented)}</strong> of{' '}
          {full.answers} answers; the validator caught them in{' '}
          <strong>{pct(full.raw_invented)}</strong> of the first drafts.
        </p>
      )}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-sm">
          <thead className="text-left text-muted">
            <tr>
              <th className="py-1 pr-3 font-medium">System</th>
              <th className="py-1 pr-3 text-right font-medium">Names books it wasn’t given</th>
              <th className="py-1 pr-3 text-right font-medium">Books it names the library doesn’t own</th>
              <th className="py-1 pr-3 text-right font-medium">Treats made-up books as real</th>
              <th className="py-1 pr-3 text-right font-medium">Talks about availability</th>
              <th className="py-1 text-right font-medium">Numbers or claims not in the record</th>
            </tr>
          </thead>
          <tbody>
            {grounding.systems.map((s) => (
              <tr key={s.name} className="border-t border-line tabular-nums">
                <th scope="row" className="py-1.5 pr-3 text-left font-normal">{NAMES[s.name] ?? s.name}</th>
                <td className="py-1.5 pr-3 text-right">{s.name === 'llm_only' ? 'n/a' : pct(s.invented)}</td>
                <td className="py-1.5 pr-3 text-right">{pct(s.unowned)}</td>
                <td className="py-1.5 pr-3 text-right">{pct(s.affirmed)}</td>
                <td className="py-1.5 pr-3 text-right">{pct(s.availability)}</td>
                <td className="py-1.5 text-right">{pct(Math.max(s.number ?? 0, s.claim ?? 0))}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted">
        Share of answers with at least one such problem, set E ({grounding.cases} cases: made-up titles, prompt
        injections in the message and in catalog text, borrowed books, everyday queries) · {grounding.llm} ·{' '}
        {grounding.git}. Checked by the same rules as the validator.
      </p>
    </div>
  )
}
