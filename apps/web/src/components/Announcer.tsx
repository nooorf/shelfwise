// The one live region. It's always in the page, so screen readers pick up
// its changes; regions created along with their text often go unannounced.
import { useSession } from '../session/store'
import { announcement } from './announce'

export function Announcer() {
  const latest = useSession((s) => s.exchanges.at(-1))
  return (
    <p className="sr-only" aria-live="polite" aria-atomic="true">
      {announcement(latest)}
    </p>
  )
}
