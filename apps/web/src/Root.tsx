import App from './App'
import { BenchPage } from './bench/BenchPage'
import { LandingPage } from './landing/LandingPage'
import { usePage } from './router'

export function Root() {
  const page = usePage()
  if (page === 'bench') return <BenchPage />
  if (page === 'landing') return <LandingPage />
  return <App /> // chat and live share today's app until their own pages land
}
