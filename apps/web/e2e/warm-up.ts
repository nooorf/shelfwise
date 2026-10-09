// The first search after the API starts loads the embedding model (tens of seconds on the
// Mac); pay that once here, not inside the first test's timeout.
export default async function warmUp(): Promise<void> {
  const response = await fetch('http://localhost:8000/api/v1/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query: 'warm up', limit: 1 }),
    signal: AbortSignal.timeout(180_000),
  })
  if (!response.ok) throw new Error(`the API did not answer a search (${response.status})`)
}
