import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { turn } from '../test/fixtures'
import { PipelineInspector } from './PipelineInspector'

const thrillers = {
  intent: 'discover' as const, semantic_query: 'thrillers', lookup: null, seed_titles: [],
  seed_work_ids: [], avoid_work_ids: [],
  constraints: [{ field: 'pages', op: 'lt' as const, value: 300, strength: 'hard' as const,
                  source: 'rule' as const, polarity: 'include' as const, span: 'under 300 pages' }],
}

describe('pipeline inspector', () => {
  it('shows the parse, the stages with scores and the timings when opened', async () => {
    const response = turn(1, {
      timings_ms: { parse: 900, retrieve: 40, narrate: 0, total: 941 },
      inspector: {
        parsed: thrillers,
        searched: thrillers,
        stages: [
          { name: 'filter', count: 812, note: 'of 5358 books pass the hard filters', top: [] },
          { name: 'dense', count: 100, note: 'cosine similarity',
            top: [{ work_id: 1, title: 'Gone Girl', score: 0.6123 }] },
          { name: 'final', count: 1, note: 'what parsed_hybrid shows',
            top: [{ work_id: 1, title: 'Gone Girl', score: null }] },
        ],
      },
    })
    render(<PipelineInspector response={response} />)

    await userEvent.click(screen.getByText('Pipeline inspector'))
    expect(screen.getByText('· parsed_hybrid · parser cascade · 941 ms')).toBeVisible()
    expect(screen.getAllByText('pages lt 300 · hard · rule')).toHaveLength(2)
    const stages = screen.getByRole('list', { name: 'Stages' })
    expect(within(stages).getByText('812')).toBeVisible()
    expect(within(stages).getByText('0.6123', { exact: false })).toBeVisible()
    expect(within(stages).getAllByText('Gone Girl', { exact: false })).toHaveLength(2)
  })

  it('invites a question before the first turn', async () => {
    render(<PipelineInspector response={undefined} />)
    await userEvent.click(screen.getByText('Pipeline inspector'))
    expect(screen.getByText('Ask something to see how it’s handled.')).toBeVisible()
  })
})
