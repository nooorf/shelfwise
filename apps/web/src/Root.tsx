import { BenchPage } from './bench/BenchPage'
import { ChatPage } from './chat/ChatPage'
import { LandingPage } from './landing/LandingPage'
import { LivePage } from './live/LivePage'
import { usePage } from './router'

export function Root() {
  const page = usePage()
  if (page === 'bench') return <BenchPage />
  if (page === 'chat') return <ChatPage />
  if (page === 'live') return <LivePage />
  return <LandingPage />
}
