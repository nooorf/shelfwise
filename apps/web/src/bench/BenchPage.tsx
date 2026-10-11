// The benchmark dashboard (design doc §22.2, §30), in the reading room: the headline numbers
// first, then every retrieval system on the dev split with 95% CIs, quality against latency,
// nDCG@10 per query category, grounding, and the parser's scores. The locked test split never
// appears here. Data: GET /api/v1/bench (eval/reports).
import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'

import { getBench } from '../api/client'
import type { Bench } from '../api/types'
import { Link } from '../components/Link'
import { SiteNav } from '../components/SiteNav'
import '../styles/site.css'
import { CategoryHeatmap } from './CategoryHeatmap'
import { GroundingTable } from './GroundingTable'
import { Leaderboard } from './Leaderboard'
import { ParetoChart } from './ParetoChart'
import { SHIPPED } from './scales'
import './bench.css'

const pct = (v: number) => `${(v * 100).toFixed(1)}%`

function Stat({ label, value, detail, lead = false }: { label: string; value: string; detail?: string; lead?: boolean }) {
  return (
    <div className={`stat ${lead ? 'is-lead' : ''}`}>
      <p className="stat-label">{label}</p>
      <p className="stat-value">{value}</p>
      {detail && <p className="stat-detail">{detail}</p>}
    </div>
  )
}

function Card({ id, title, intro, children }: { id: string; title: string; intro?: ReactNode; children: ReactNode }) {
  return (
    <section aria-labelledby={id} className="bench-card">
      <div className="bench-card-head">
        <h2 id={id}>{title}</h2>
        {intro && <p>{intro}</p>}
      </div>
      {children}
    </section>
  )
}

export function BenchPage() {
  const [bench, setBench] = useState<Bench | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    getBench().then(setBench).catch(() => setFailed(true))
  }, [])

  const retrieval = bench?.retrieval
  const parser = bench?.parser
  const shipped = retrieval?.systems.find((s) => s.name === SHIPPED)
  const grounded = bench?.grounding?.systems.find((s) => s.name === 'full')

  return (
    <div className="reading-room site bench">
      <SiteNav>
        <Link href="/chat" className="btn btn-butter">Chat</Link>
        <Link href="/live" className="btn btn-coral">Live session</Link>
      </SiteNav>

      <main className="bench-main">
        <header className="bench-hero">
          <p className="bench-eyebrow">Benchmarks</p>
          <h1 className="bench-title">How well it finds books.</h1>
          <p className="bench-sub">
            Every number here comes from real requests graded by hand, on the dev split. The locked
            test split is kept out of sight until the final run.
          </p>
          {failed && <p role="alert" className="bench-alert">Couldn’t load the reports. Is the API running?</p>}
          {bench && !retrieval && !parser && (
            <p className="bench-alert">No reports yet: run <code>make eval</code> and <code>make eval-parser</code>.</p>
          )}
          {(shipped || grounded || parser) && (
            <div className="stats">
              {shipped && (
                <Stat
                  label="Ranking quality, nDCG@10"
                  value={shipped.ndcg.mean.toFixed(3)}
                  detail={`95% CI ${shipped.ndcg.ci95[0].toFixed(2)}–${shipped.ndcg.ci95[1].toFixed(2)}, the system in the app`}
                />
              )}
              {grounded?.invented != null && (
                <Stat
                  lead
                  label="Invented books shown to readers"
                  value={pct(grounded.invented)}
                  detail={`of ${grounded.answers} answers; first drafts had ${pct(grounded.raw_invented ?? 0)}${grounded.invented === 0 ? ', all caught' : ''}`}
                />
              )}
              {parser && (
                <Stat
                  label="Constraints read right, F1"
                  value={pct(parser.constraint_f1)}
                  detail={`precision ${pct(parser.constraint_precision)} · recall ${pct(parser.constraint_recall)}`}
                />
              )}
              {shipped?.latency_ms && (
                <Stat label="Search time, p95" value={`${shipped.latency_ms.p95} ms`} detail="per query, on an 8 GB M2 Mac" />
              )}
            </div>
          )}
          {retrieval && (
            <p className="bench-meta">
              Dev split, {retrieval.queries} queries · embeddings {retrieval.embedding_model ?? '?'} · parser{' '}
              {retrieval.parser ?? 'rules'} · {retrieval.git} · {new Date(retrieval.created).toLocaleString()}
            </p>
          )}
        </header>

        {retrieval && (
          <>
            <Card id="leaderboard" title="Leaderboard" intro="nDCG@10 with its 95% confidence interval, best first, and the other ranking metrics.">
              <Leaderboard systems={retrieval.systems} />
            </Card>
            <Card
              id="pareto"
              title="Quality against latency"
              intro="p95 wall time per query on the dev Mac (log scale). The line joins the systems no other beats on both; the parsed systems read cached LLM answers, so their parse time isn’t included."
            >
              <ParetoChart systems={retrieval.systems} />
            </Card>
            <Card id="categories" title="By kind of request" intro="nDCG@10 per query category: darker is better.">
              <CategoryHeatmap systems={retrieval.systems} />
            </Card>
          </>
        )}

        {bench?.grounding && (
          <Card id="grounding" title="Grounding: what reaches the reader">
            <GroundingTable grounding={bench.grounding} />
          </Card>
        )}

        {parser && (
          <Card
            id="parser"
            title="Query parser"
            intro={`${parser.parser} parser${parser.model ? ` with ${parser.model}` : ''} on gold set B (${parser.split}, ${parser.queries} queries) · ${parser.git}`}
          >
            <div className="stats is-small">
              <Stat label="Intent accuracy" value={pct(parser.intent_accuracy)} />
              <Stat label="Exact match" value={pct(parser.exact_match)} />
              <Stat
                label="Constraint F1"
                value={pct(parser.constraint_f1)}
                detail={`P ${pct(parser.constraint_precision)} · R ${pct(parser.constraint_recall)}`}
              />
            </div>
          </Card>
        )}
      </main>
    </div>
  )
}
