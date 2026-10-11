// Pipeline inspector (design doc §22.1, §22.2): a developer strip showing how the last turn was
// read, what was searched, the candidates at each stage with their scores, and the timings.
import type { components } from '../api/schema'
import type { TurnResponse } from '../api/types'

type Parsed = components['schemas']['ParsedRequest']
type Constraint = components['schemas']['Constraint']

const STAGE_NAMES: Record<string, string> = {
  filter: 'Hard filters', bm25: 'BM25', dense: 'Dense', seed: 'Near the seed',
  fused: 'Fused + nudges', final: 'Shown',
}

function constraintText(c: Constraint): string {
  const value = Array.isArray(c.value) ? c.value.join(' | ') : String(c.value)
  return `${c.polarity === 'exclude' ? 'not ' : ''}${c.field} ${c.op} ${value} · ${c.strength} · ${c.source}`
}

function Request({ title, request }: { title: string; request: Parsed | null }) {
  if (!request) return null
  const seeds = request.seed_titles ?? []
  const constraints = request.constraints ?? []
  return (
    <section className="min-w-56 flex-1">
      <h3 className="mb-1 font-semibold">{title}</h3>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
        <dt className="text-muted">intent</dt>
        <dd>{request.intent}</dd>
        <dt className="text-muted">semantic</dt>
        <dd>{request.semantic_query || '—'}</dd>
        {request.lookup && (
          <>
            <dt className="text-muted">lookup</dt>
            <dd>{[request.lookup.title, request.lookup.author].filter(Boolean).join(' · ')}</dd>
          </>
        )}
        {seeds.length > 0 && (
          <>
            <dt className="text-muted">seeds</dt>
            <dd>{seeds.join(', ')}</dd>
          </>
        )}
        <dt className="text-muted">constraints</dt>
        <dd>
          {constraints.length === 0 ? '—' : (
            <ul>{constraints.map((c, i) => <li key={i}>{constraintText(c)}</li>)}</ul>
          )}
        </dd>
      </dl>
    </section>
  )
}

/** `inline`: under one chat reply, titled "How it searched", instead of a strip along the
 * bottom of the page. */
export function PipelineInspector({ response, inline = false }: { response: TurnResponse | undefined; inline?: boolean }) {
  return (
    <details className={inline ? 'inspector-inline text-xs' : 'border-t border-line bg-card text-xs'}>
      <summary className="cursor-pointer px-4 py-2 text-muted select-none hover:text-ink md:px-6">
        {inline ? 'How it searched' : 'Pipeline inspector'}
        {response && (
          <span className="ml-2 tabular-nums">
            · {response.system ?? response.route} · parser {response.parser} · {response.timings_ms.total} ms
          </span>
        )}
      </summary>
      <p className="px-4 pb-2 md:px-6">
        <a href="/bench" className="text-accent hover:underline">Benchmarks: every system on the dev split →</a>
      </p>
      {!response ? (
        <p className="px-4 pb-3 text-muted md:px-6">Ask something to see how it’s handled.</p>
      ) : (
        <div className="flex max-h-[45vh] flex-col gap-4 overflow-y-auto px-4 pb-4 md:px-6">
          <p className="tabular-nums">
            {Object.entries(response.timings_ms).map(([stage, ms]) => `${stage} ${ms} ms`).join(' · ')}
            {response.parse_error && <span className="text-out"> · parse fell back: {response.parse_error}</span>}
          </p>
          <div className="flex flex-wrap gap-6">
            <Request title="This message, parsed" request={response.inspector.parsed ?? null} />
            <Request title="Searched (merged state)" request={response.inspector.searched ?? null} />
          </div>
          {response.inspector.stages.length > 0 && (
            <ol aria-label="Stages" className="flex gap-4 overflow-x-auto pb-1">
              {response.inspector.stages.map((stage, i) => (
                <li key={i} className="w-56 shrink-0">
                  <h3 className="font-semibold">
                    {STAGE_NAMES[stage.name] ?? stage.name}{' '}
                    <span className="font-normal text-muted tabular-nums">{stage.count}</span>
                  </h3>
                  <p className="mb-1 text-muted">{stage.note}</p>
                  <ol className="list-decimal pl-5">
                    {stage.top.map((hit) => (
                      <li key={hit.work_id}>
                        {hit.title}
                        {hit.score != null && <span className="text-muted tabular-nums"> {hit.score}</span>}
                      </li>
                    ))}
                  </ol>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </details>
  )
}
