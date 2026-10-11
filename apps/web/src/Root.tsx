import App from './App'
import { BenchPage } from './bench/BenchPage'
import { ChatPage } from './chat/ChatPage'
import { LandingPage } from './landing/LandingPage'
import { usePage } from './router'

export function Root() {
  const page = usePage()
  if (page === 'bench') return <BenchPage />
  if (page === 'landing') return <LandingPage />
  if (page === 'chat') return <ChatPage />
  return <App /> // the live session keeps today's app until its own page lands
}
