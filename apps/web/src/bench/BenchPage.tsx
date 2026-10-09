// The benchmark dashboard (design doc §22.2, §30): every retrieval system on the dev split
// with 95% CIs, nDCG@10 per query category, quality against latency, and the parser's scores.
// The locked test split never appears here. Data: GET /api/v1/bench (eval/reports).
import { useEffect, useState } from 'react'

import { getBench } from '../api/client'
import type { Bench } from '../api/types'
import { CategoryHeatmap } from './CategoryHeatmap'
import { GroundingTable } from './GroundingTable'
import { Leaderboard } from './Leaderboard'
import { ParetoChart } from './ParetoChart'

function Tile({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return (
    <div className="rounded-lg border border-line bg-card px-4 py-3">
      <p className="text-sm text-muted">{label}</p>
      <p className="font-serif text-2xl tabular-nums">{value}</p>
      {detail && <p className="text-xs text-muted tabular-nums">{detail}</p>}
    </div>
  )
}

const pct = (v: number) => `${(v * 100).toFixed(1)}%`

export function BenchPage() {
  const [bench, setBench] = useState<Bench | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    getBench().then(setBench).catch(() => setFailed(true))
  }, [])

  const retrieval = bench?.retrieval
  const parser = bench?.parser
  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-8 p-4 md:p-8">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="font-serif text-2xl font-semibold">Shelfwise benchmarks</h1>
        <a href="/" className="text-sm text-accent hover:underline">Back to the app</a>
      </header>
      {failed && <p role="alert" className="text-out">Couldn’t load the reports. Is the API running?</p>}
      {bench && !retrieval && !parser && (
        <p className="text-muted">No reports yet: run <code>make eval</code> and <code>make eval-parser</code>.</p>
      )}

      {retrieval && (
        <>
          <p className="text-sm text-muted">
            Dev split, {retrieval.queries} queries · embeddings {retrieval.embedding_model ?? '?'} · parser{' '}
            {retrieval.parser ?? 'rules'} · {retrieval.git} · {new Date(retrieval.created).toLocaleString()}
          </p>
          <section aria-labelledby="leaderboard" className="flex flex-col gap-3">
            <h2 id="leaderboard" className="text-lg font-semibold">Leaderboard: nDCG@10 with 95% CI</h2>
            <Leaderboard systems={retrieval.systems} />
          </section>
          <section aria-labelledby="pareto" className="flex flex-col gap-3">
            <h2 id="pareto" className="text-lg font-semibold">Quality against latency</h2>
            <p className="text-sm text-muted">
              p95 wall time per query on the dev Mac (log scale). The line joins systems no other beats on
              both; the parsed systems read cached LLM answers, so their parse time isn’t included.
            </p>
            <ParetoChart systems={retrieval.systems} />
          </section>
          <section aria-labelledby="categories" className="flex flex-col gap-3">
            <h2 id="categories" className="text-lg font-semibold">nDCG@10 by query category</h2>
            <CategoryHeatmap systems={retrieval.systems} />
          </section>
        </>
      )}

      {bench?.grounding && (
        <section aria-labelledby="grounding" className="flex flex-col gap-3">
          <h2 id="grounding" className="text-lg font-semibold">Grounding: what reaches the reader</h2>
          <GroundingTable grounding={bench.grounding} />
        </section>
      )}

      {parser && (
        <section aria-labelledby="parser" className="flex flex-col gap-3">
          <h2 id="parser" className="text-lg font-semibold">Query parser</h2>
          <p className="text-sm text-muted">
            {parser.parser} parser{parser.model ? ` with ${parser.model}` : ''} on gold set B ({parser.split},{' '}
            {parser.queries} queries) · {parser.git}
          </p>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Tile label="Intent accuracy" value={pct(parser.intent_accuracy)} />
            <Tile label="Exact match" value={pct(parser.exact_match)} />
            <Tile
              label="Constraint F1"
              value={pct(parser.constraint_f1)}
              detail={`P ${pct(parser.constraint_precision)} · R ${pct(parser.constraint_recall)}`}
            />
          </div>
        </section>
      )}
    </div>
  )
}
