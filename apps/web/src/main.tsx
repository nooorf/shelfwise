import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { BenchPage } from './bench/BenchPage'
import { ErrorBoundary } from './components/ErrorBoundary'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      {window.location.pathname.startsWith('/bench') ? <BenchPage /> : <App />}
    </ErrorBoundary>
  </StrictMode>,
)
